from __future__ import annotations

import copy
import json
import logging
import time
import uuid
from typing import Any, Callable, Optional

from apps.platform.ai.services.tools.base import BaseTool
from apps.platform.ai.services.tools.registry import ToolRegistry
from apps.platform.ai.services.tools.resolver import ToolResolver
from apps.platform.ai.services.tools.result import ToolContext, ToolResult

logger = logging.getLogger(__name__)

# Session key for active plan storage
_SESSION_PLANS_KEY = "ai_active_plans"


class ExecutionEngine:
    """
    Orchestrates tool execution with confirmation, dry-run, and multi-step plans.

    Flow:
      1. Resolve intent → tool + params
      2. If dry_run requested → call tool.dry_run() instead of execute()
      3. If tool requires_confirmation → return result with confirmation_token
      4. On confirmation call → tool.execute() with confirmed flag
      5. For multi-step plans → execute each step in sequence

    Usage:
        engine = ExecutionEngine()
        result = engine.run(intent, request)
        if result.requires_confirmation:
            result = engine.confirm_and_execute(result.confirmation_token, intent, request)

    Plan Lifecycle:
        plan = engine.create_plan(question, intent)
        engine.execute_plan(plan, request, progress_callback)
        # On confirmation required: plan.status == "paused"
        engine.confirm_plan_step(plan_id, token, request)
        engine.resume_plan(plan_id, request, progress_callback)
        # On failure: plan.status == "failed"
        engine.retry_failed_step(plan_id, request, progress_callback)
        engine.cancel_plan(plan_id, request)
    """

    def __init__(self):
        self.registry = ToolRegistry.get_instance()
        self.registry.discover()
        self.resolver = ToolResolver()

    def run(
        self,
        intent: Any,
        request: Any = None,
        dry_run: bool = False,
        confirmation_token: str = "",
    ) -> ToolResult:
        """
        Resolve intent and execute the best tool.
        """
        tool, params = self.resolver.resolve(intent)
        if tool is None:
            return ToolResult(
                success=False,
                tool="none",
                summary="No se encontro una herramienta para esta solicitud.",
                error="No matching tool found",
                error_code="NO_TOOL",
                followups=[
                    "¿Que herramientas estan disponibles?",
                    "Pregunta de otra forma",
                ],
            )

        ctx = ToolContext(
            user=getattr(request, "user", None),
            request=request,
            session=getattr(request, "session", {}),
            intent=intent,
            dry_run=dry_run,
            confirmation_token=confirmation_token,
        )

        if confirmation_token:
            if ctx.is_confirmed(confirmation_token):
                confirmed_ctx = ctx
                return self._do_execute(tool, confirmed_ctx, params)
            else:
                return ToolResult(
                    success=False,
                    tool=tool.name,
                    summary="Accion no confirmada.",
                    error="Not confirmed",
                    error_code="NOT_CONFIRMED",
                    confirmation_token=confirmation_token,
                    requires_confirmation=True,
                    confirmation_message="Esta accion requiere confirmacion. Envia el token de confirmacion para ejecutar.",
                )

        if dry_run and tool.dry_run_supported:
            return self._do_dry_run(tool, ctx, params)

        if tool.requires_confirmation:
            dry_result = self._do_dry_run(tool, ctx, params)
            token = ctx.make_confirmation_token()
            ctx.store_dry_run_result(token, tool.name, params, dry_result)
            return ToolResult(
                success=True,
                tool=tool.name,
                summary=dry_result.summary,
                details=dry_result.details,
                requires_confirmation=True,
                confirmation_token=token,
                confirmation_message=dry_result.summary,
                dry_run=dry_result.dry_run,
                dry_run_summary=dry_result.summary,
                followups=dry_result.followups,
                execution_time_ms=dry_result.execution_time_ms,
            )

        return self._do_execute(tool, ctx, params)

    def confirm_and_execute(
        self,
        token: str,
        intent: Any,
        request: Any,
    ) -> ToolResult:
        """
        Confirm and execute a previously dry-run tool.
        """
        session = getattr(request, "session", {})
        key = f"tool_confirmation_{token}"
        entry = session.get(key)
        if entry is None:
            return ToolResult(
                success=False,
                tool="unknown",
                summary="Token de confirmacion invalido o expirado.",
                error="Invalid confirmation token",
                error_code="INVALID_TOKEN",
            )

        tool_name = entry.get("tool", "")
        params = entry.get("params", {})

        tool = self.registry.get_tool(tool_name)
        if tool is None:
            return ToolResult(
                success=False,
                tool=tool_name,
                summary="Herramienta no encontrada en el registro.",
                error="Tool not found",
                error_code="TOOL_NOT_FOUND",
            )

        ctx = ToolContext(
            user=getattr(request, "user", None),
            request=request,
            session=session,
            intent=intent,
        )
        ctx.confirm_action(token)

        result = self._do_execute(tool, ctx, params)
        session.pop(key, None)
        return result

    def _do_execute(self, tool: BaseTool, ctx: ToolContext, params: dict) -> ToolResult:
        t0 = time.perf_counter()
        try:
            result = tool.execute(ctx, params)
            result.execution_time_ms = (time.perf_counter() - t0) * 1000
            result.tool = tool.name
            if not result.followups:
                result.followups = [
                    "¿Que mas necesitas?",
                    "¿Necesitas ayuda con otra cosa?",
                    "Muéstrame el resultado en detalle",
                ]
            return result
        except Exception as e:
            logger.exception("Tool %s execution error", tool.name)
            return ToolResult(
                success=False,
                tool=tool.name,
                summary=f"Error al ejecutar {tool.description}: {e}",
                error=str(e),
                error_code="EXECUTION_ERROR",
                execution_time_ms=(time.perf_counter() - t0) * 1000,
                followups=["Intenta de nuevo", "Reporta este error"],
            )

    def _do_dry_run(self, tool: BaseTool, ctx: ToolContext, params: dict) -> ToolResult:
        t0 = time.perf_counter()
        try:
            result = tool.dry_run(ctx, params)
            result.execution_time_ms = (time.perf_counter() - t0) * 1000
            result.dry_run = True
            result.tool = tool.name
            return result
        except Exception as e:
            logger.exception("Tool %s dry_run error", tool.name)
            return ToolResult(
                success=False,
                tool=tool.name,
                summary=f"Error en previsualización: {e}",
                error=str(e),
                error_code="DRY_RUN_ERROR",
            )

    # ═══════════════════════════════════════════════════════════════
    # Plan Lifecycle
    # ═══════════════════════════════════════════════════════════════

    def create_plan(
        self,
        question: str,
        intent: Any,
        request: Any = None,
    ) -> Optional["Plan"]:
        """
        Create a Plan using TaskPlanner.

        Returns None if the plan has no steps.
        """
        try:
            from apps.platform.ai.services.planner import TaskPlanner
            planner = TaskPlanner()
            extra_context = {"request": request} if request else {}
            plan = planner.create_plan(question, intent, extra_context)
            if not plan.steps:
                return None
            plan.status = "ready"
            self._save_plan(plan, request)
            return plan
        except Exception as e:
            logger.exception("Failed to create plan")
            return None

    def execute_plan(
        self,
        plan: "Plan",
        request: Any,
        progress_callback: Optional[Callable] = None,
    ) -> "Plan":
        """
        Execute a Plan step by step.

        For each step:
          1. Emit status via progress_callback
          2. Resolve tool + params
          3. Execute tool
          4. If confirmation required → pause plan, return
          5. If failure → mark failed, stop remaining, return
          6. Store outputs in plan.context
          7. Mark next steps as READY
          8. Save plan state to session

        The progress_callback receives (event_type: str, data: dict).
        Event types: plan_start, plan_step, plan_step_done, plan_step_confirmation,
                     plan_paused, plan_complete, plan_failed, plan_error
        """
        plan_meta = getattr(plan, "metrics", {})
        plan_meta["execution_start"] = time.time()
        plan.status = "running"

        self._emit(progress_callback, "plan_start", {
            "plan_id": plan.id,
            "total_steps": len(plan.steps),
            "steps": [s.to_dict() for s in plan.steps],
        })
        self._save_plan(plan, request)

        for i, step in enumerate(plan.steps):
            if step.status in (StepStatus.SUCCESS, StepStatus.SKIPPED):
                continue
            if step.status == StepStatus.CANCELLED:
                break
            if step.status == StepStatus.FAILED and i > plan.current_step:
                break

            plan.current_step = i
            step.status = StepStatus.RUNNING

            self._emit(progress_callback, "plan_step", {
                "plan_id": plan.id,
                "step_num": step.step_num,
                "tool_name": step.tool_name,
                "description": step.description,
                "total_steps": len(plan.steps),
            })
            self._save_plan(plan, request)

            # ── Resolve tool ──
            tool = self.registry.get_tool(step.tool_name)
            if tool is None:
                step.status = StepStatus.FAILED
                step.error_message = f"Herramienta '{step.tool_name}' no encontrada"
                self._on_step_failed(plan, step, progress_callback)
                break

            # ── Build params from plan context ──
            params = dict(step.params)
            for dep_key in step.depends_on:
                if dep_key in plan.context:
                    params[dep_key] = plan.context[dep_key]

            # ── Execute tool ──
            step_t0 = time.perf_counter()

            # Check if this tool requires confirmation (check metadata + tool attr)
            meta = self._get_step_meta(step)
            requires_confirmation = meta.get("requires_confirmation", False) or tool.requires_confirmation

            if requires_confirmation:
                # Dry-run first
                dry_ctx = ToolContext(
                    user=getattr(request, "user", None),
                    request=request,
                    session=getattr(request, "session", {}),
                    intent=getattr(plan, "_intent", None),
                    dry_run=True,
                )
                dry_result = self._do_dry_run(tool, dry_ctx, params)
                token = dry_ctx.make_confirmation_token()
                dry_ctx.store_dry_run_result(token, tool.name, params, dry_result)

                step.status = StepStatus.PAUSED
                step.requires_confirmation = True
                step.confirmation_token = token
                step.result = dry_result
                step.execution_time_ms = (time.perf_counter() - step_t0) * 1000

                plan.status = "paused"
                self._save_plan(plan, request)

                self._emit(progress_callback, "plan_step_confirmation", {
                    "plan_id": plan.id,
                    "step_num": step.step_num,
                    "tool_name": step.tool_name,
                    "description": step.description,
                    "confirmation_token": token,
                    "summary": dry_result.summary if dry_result else "",
                })
                self._emit(progress_callback, "plan_paused", {
                    "plan_id": plan.id,
                    "step_num": step.step_num,
                    "reason": f"Esperando confirmacion para: {step.description}",
                })
                return plan

            # ── Normal execution ──
            ctx = ToolContext(
                user=getattr(request, "user", None),
                request=request,
                session=getattr(request, "session", {}),
                intent=getattr(plan, "_intent", None),
            )

            result = self._do_execute(tool, ctx, params)
            step.result = result
            step.execution_time_ms = (time.perf_counter() - step_t0) * 1000

            if result.success:
                step.status = StepStatus.SUCCESS

                # Store outputs in plan context
                if step.produces:
                    for key in step.produces:
                        output_value = self._extract_output(result, key, step.tool_name)
                        plan.context[key] = output_value
                        step.output = type("StepOutput", (), {"key": key, "value": output_value})()

                self._emit(progress_callback, "plan_step_done", {
                    "plan_id": plan.id,
                    "step_num": step.step_num,
                    "tool_name": step.tool_name,
                    "success": True,
                    "summary": result.summary[:200] if result.summary else "",
                    "execution_time_ms": step.execution_time_ms,
                })

                # Mark next steps as READY
                self._mark_next_ready(plan, i)
            else:
                step.status = StepStatus.FAILED
                step.error_message = result.summary or result.error
                self._on_step_failed(plan, step, progress_callback, result)
                break

            self._save_plan(plan, request)

        # ── Plan complete or fully failed ──
        plan_meta["execution_end"] = time.time()
        plan.total_duration_ms = (time.time() - plan_meta.get("execution_start", time.time())) * 1000

        all_passed = all(s.status == StepStatus.SUCCESS for s in plan.steps)
        any_failed = any(s.status == StepStatus.FAILED for s in plan.steps)
        any_cancelled = any(s.status == StepStatus.CANCELLED for s in plan.steps)

        if all_passed:
            plan.status = "completed"
            self._emit(progress_callback, "plan_complete", {
                "plan_id": plan.id,
                "total_steps": len(plan.steps),
                "total_duration_ms": round(plan.total_duration_ms, 1),
            })
        elif any_cancelled:
            plan.status = "cancelled"
            self._emit(progress_callback, "plan_cancelled", {
                "plan_id": plan.id,
                "step_num": plan.current_step,
            })
        elif any_failed:
            plan.status = "failed"

        self._save_plan(plan, request)
        return plan

    def confirm_plan_step(self, plan_id: str, token: str, request: Any) -> Optional["Plan"]:
        """
        Confirm a paused plan step and continue execution.

        Returns the updated Plan, or None if not found.
        """
        plan = self._load_plan(plan_id, request)
        if plan is None:
            return None

        step = self._find_paused_step(plan)
        if step is None:
            return None

        if step.confirmation_token != token:
            return plan

        session = getattr(request, "session", {})
        key = f"tool_confirmation_{token}"
        entry = session.get(key)
        if entry is None:
            return plan

        tool = self.registry.get_tool(step.tool_name)
        if tool is None:
            step.status = StepStatus.FAILED
            step.error_message = f"Herramienta '{step.tool_name}' no encontrada"
            plan.status = "failed"
            self._save_plan(plan, request)
            return plan

        # Confirm in session
        ctx = ToolContext(
            user=getattr(request, "user", None),
            request=request,
            session=session,
        )
        ctx.confirm_action(token)

        # Execute the confirmed step
        params = dict(step.params)
        step_t0 = time.perf_counter()
        result = self._do_execute(tool, ctx, params)
        step.result = result
        step.execution_time_ms = (time.perf_counter() - step_t0) * 1000

        if result.success:
            step.status = StepStatus.SUCCESS
            if step.produces:
                for key in step.produces:
                    output_value = self._extract_output(result, key, step.tool_name)
                    plan.context[key] = output_value
        else:
            step.status = StepStatus.FAILED
            step.error_message = result.summary or result.error

        session.pop(key, None)
        plan.status = "running"
        self._save_plan(plan, request)
        return plan

    def resume_plan(
        self,
        plan_id: str,
        request: Any,
        progress_callback: Optional[Callable] = None,
    ) -> Optional["Plan"]:
        """
        Resume a paused plan from its current step.

        Returns the updated Plan, or None if not found.
        """
        plan = self._load_plan(plan_id, request)
        if plan is None:
            return None
        if plan.status not in ("paused",):
            return plan

        plan.status = "running"
        self._emit(progress_callback, "plan_resumed", {
            "plan_id": plan.id,
            "step_num": plan.current_step,
        })
        self._save_plan(plan, request)
        return self.execute_plan(plan, request, progress_callback)

    def cancel_plan(self, plan_id: str, request: Any) -> Optional["Plan"]:
        """Cancel all remaining steps in a plan."""
        plan = self._load_plan(plan_id, request)
        if plan is None:
            return None

        for s in plan.steps:
            if s.status in (StepStatus.PENDING, StepStatus.READY, StepStatus.RUNNING):
                s.status = StepStatus.CANCELLED

        plan.status = "cancelled"
        self._save_plan(plan, request)
        return plan

    def retry_failed_step(
        self,
        plan_id: str,
        request: Any,
        progress_callback: Optional[Callable] = None,
    ) -> Optional["Plan"]:
        """
        Retry the last failed step in a plan.

        Resets the failed step to READY, marks subsequent steps back to PENDING,
        and re-executes from that step.

        Returns the updated Plan, or None if not found.
        """
        plan = self._load_plan(plan_id, request)
        if plan is None:
            return None

        failed_idx = None
        for i, s in enumerate(plan.steps):
            if s.status == StepStatus.FAILED:
                failed_idx = i
                break

        if failed_idx is None:
            return plan

        # Reset this step and all after it
        step = plan.steps[failed_idx]
        step.status = StepStatus.READY
        step.error_message = ""
        step.result = None
        step.execution_time_ms = 0.0

        for j in range(failed_idx + 1, len(plan.steps)):
            plan.steps[j].status = StepStatus.PENDING
            plan.steps[j].result = None
            plan.steps[j].error_message = ""

        # Remove context keys produced by failed step and subsequent steps
        for j in range(failed_idx, len(plan.steps)):
            for key in plan.steps[j].produces:
                plan.context.pop(key, None)

        plan.status = "running"
        plan.current_step = failed_idx

        self._emit(progress_callback, "plan_retry", {
            "plan_id": plan.id,
            "step_num": step.step_num,
            "tool_name": step.tool_name,
            "description": f"Reintentando: {step.description}",
        })

        self._save_plan(plan, request)
        return self.execute_plan(plan, request, progress_callback)

    def get_plan(self, plan_id: str, request: Any) -> Optional["Plan"]:
        """Retrieve a plan from session storage."""
        return self._load_plan(plan_id, request)

    def list_plans(self, request: Any) -> list[dict]:
        """List all active plans in session."""
        session = getattr(request, "session", {})
        plans_store = session.get(_SESSION_PLANS_KEY, {})
        return [p.get("plan", {}) for p in plans_store.values()]

    # ═══════════════════════════════════════════════════════════════
    # Internal helpers
    # ═══════════════════════════════════════════════════════════════

    def _on_step_failed(
        self,
        plan: "Plan",
        step: "PlanStep",
        progress_callback: Optional[Callable],
        result: Optional[ToolResult] = None,
    ) -> None:
        """Handle a step failure: suggest recovery, cancel remaining steps."""
        for s in plan.steps:
            if s.status in (StepStatus.PENDING, StepStatus.READY):
                s.status = StepStatus.CANCELLED

        plan.status = "failed"

        error_detail = result.summary if result else step.error_message
        summary = f"Paso {step.step_num} ({step.tool_name}) fallo: {step.error_message}"

        self._emit(progress_callback, "plan_failed", {
            "plan_id": plan.id,
            "step_num": step.step_num,
            "tool_name": step.tool_name,
            "error": step.error_message,
            "error_detail": error_detail,
            "suggestion": self._get_recovery_suggestion(step),
        })
        self._save_plan(plan, request)

    def _get_recovery_suggestion(self, step: "PlanStep") -> str:
        """Generate a recovery suggestion for a failed step."""
        suggestions = {
            "import_records": "Verifica que el archivo Excel sea valido y que los campos coincidan.",
            "create_form": "Verifica que el nombre del formulario no exista ya.",
            "analyze_document": "Verifica que el documento sea legible y este en un formato soportado.",
            "inventory_queries": "Verifica que existan productos con datos de inventario.",
            "sales_queries": "Verifica que existan ventas registradas.",
        }
        return suggestions.get(step.tool_name, "Revisa los parametros e intenta de nuevo.")

    def _mark_next_ready(self, plan: "Plan", current_idx: int) -> None:
        """Mark the next step as READY if all its dependencies are met."""
        if current_idx + 1 >= len(plan.steps):
            return
        next_step = plan.steps[current_idx + 1]
        if next_step.status != StepStatus.PENDING:
            return
        deps_met = all(k in plan.context for k in next_step.depends_on)
        if deps_met:
            next_step.status = StepStatus.READY

    def _find_paused_step(self, plan: "Plan") -> Optional["PlanStep"]:
        for s in plan.steps:
            if s.status == StepStatus.PAUSED:
                return s
        return None

    def _extract_output(self, result: ToolResult, key: str, tool_name: str) -> Any:
        """Extract a named output from a ToolResult based on key and tool."""
        # Try details dict first
        if result.details and key in result.details:
            return result.details[key]

        # Tool-specific extraction
        extractors = {
            "create_form": lambda: result.details.get("form_id", result.details.get("id")),
            "import_records": lambda: {
                "summary": result.summary,
                "created": result.details.get("validas", 0),
                "errors": result.details.get("errores", 0),
            },
            "search_records": lambda: result.details,
            "inventory_queries": lambda: result.details,
            "sales_queries": lambda: result.details,
        }

        extractor = extractors.get(tool_name)
        if extractor:
            return extractor()

        return result.summary

    def _get_step_meta(self, step: "PlanStep") -> dict:
        try:
            from apps.platform.ai.services.planner import TaskPlanner
            planner = TaskPlanner()
            return planner.get_step_metadata(step)
        except Exception:
            return {}

    def _emit(self, callback: Optional[Callable], event: str, data: dict) -> None:
        """Emit a progress event via the callback, if provided."""
        if callback:
            try:
                callback(event, data)
            except Exception as e:
                logger.warning("Progress callback error: %s", e)

    def _save_plan(self, plan: "Plan", request: Any) -> None:
        """Save plan state to session so it survives pause/resume."""
        session = getattr(request, "session", {})
        if session is None:
            return
        plans_store = session.get(_SESSION_PLANS_KEY, {})
        plans_store[plan.id] = {
            "plan": plan.to_dict(),
            "context": plan.context,
            "steps": [s.to_dict() for s in plan.steps],
            "status": plan.status,
            "current_step": plan.current_step,
            "saved_at": time.time(),
        }
        # Store the full objects too for in-memory resume
        plans_store[f"{plan.id}_full"] = {
            "plan_obj": plan,
            "step_objs": plan.steps,
        }
        session[_SESSION_PLANS_KEY] = plans_store

    def _load_plan(self, plan_id: str, request: Any) -> Optional["Plan"]:
        """Load a plan from session storage."""
        from apps.platform.ai.services.planner import Plan, PlanStep, StepStatus

        session = getattr(request, "session", {})
        plans_store = session.get(_SESSION_PLANS_KEY, {})
        full_key = f"{plan_id}_full"
        entry = plans_store.get(full_key)
        if entry:
            return entry.get("plan_obj")

        # Fallback: rebuild from serialized dict
        serialized = plans_store.get(plan_id)
        if serialized is None:
            return None

        plan = Plan(
            id=plan_id,
            question=serialized.get("plan", {}).get("question", ""),
            context=serialized.get("context", {}),
            status=serialized.get("status", "pending"),
            current_step=serialized.get("current_step", 0),
        )
        for s_data in serialized.get("steps", []):
            step = PlanStep(
                step_num=s_data["step_num"],
                tool_name=s_data["tool_name"],
                description=s_data.get("description", ""),
                status=StepStatus(s_data.get("status", "pending")),
                error_message=s_data.get("error_message", ""),
                execution_time_ms=s_data.get("execution_time_ms", 0.0),
            )
            plan.steps.append(step)

        # Save back as full
        plans_store[full_key] = {"plan_obj": plan, "step_objs": plan.steps}
        session[_SESSION_PLANS_KEY] = plans_store
        return plan
