from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from apps.platform.ai.services.decision_engine import ChatIntent
from apps.platform.ai.services.decision_engine import ChatIntent

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
# Plan dataclasses
# ═══════════════════════════════════════════════════════════════════


class StepStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"          # awaiting user confirmation
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


@dataclass
class StepOutput:
    """Output produced by a single plan step."""
    key: str                     # e.g. "form_id", "import_summary", "inventory_result"
    value: Any
    description: str = ""


@dataclass
class PlanStep:
    """A single step within a Plan."""
    step_num: int
    tool_name: str
    description: str
    params: dict[str, Any] = field(default_factory=dict)
    status: StepStatus = StepStatus.PENDING
    result: Optional[ToolResult] = None
    requires_confirmation: bool = False
    confirmation_token: str = ""
    depends_on: list[str] = field(default_factory=list)   # output keys this step needs
    produces: list[str] = field(default_factory=list)      # output keys this step produces
    error_message: str = ""
    execution_time_ms: float = 0.0
    output: Optional[StepOutput] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_num": self.step_num,
            "tool_name": self.tool_name,
            "description": self.description,
            "status": self.status.value,
            "requires_confirmation": self.requires_confirmation,
            "confirmation_token": self.confirmation_token,
            "depends_on": self.depends_on,
            "produces": self.produces,
            "error_message": self.error_message,
            "execution_time_ms": round(self.execution_time_ms, 1),
            "output_key": self.output.key if self.output else None,
        }


@dataclass
class Plan:
    """A multi-step execution plan."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    question: str = ""
    steps: list[PlanStep] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)  # shared step outputs: key -> value
    status: str = "pending"   # pending, running, paused, completed, failed, cancelled
    error: str = ""
    total_duration_ms: float = 0.0
    current_step: int = 0
    created_at: float = field(default_factory=time.time)
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "question": self.question,
            "steps": [s.to_dict() for s in self.steps],
            "status": self.status,
            "error": self.error,
            "total_duration_ms": round(self.total_duration_ms, 1),
            "current_step": self.current_step,
        }


# ═══════════════════════════════════════════════════════════════════
# Tool metadata
# ═══════════════════════════════════════════════════════════════════

_TOOL_METADATA: dict[str, dict[str, Any]] = {
    "create_form": {
        "estimated_duration_ms": 2000,
        "requires_confirmation": False,
        "required_inputs": [],
        "produced_outputs": ["form_id", "form_name"],
        "side_effects": ["create_db_record"],
    },
    "import_records": {
        "estimated_duration_ms": 15000,
        "requires_confirmation": True,
        "required_inputs": ["form_id", "file_path"],
        "produced_outputs": ["import_summary", "created_count", "error_count"],
        "side_effects": ["create_db_records"],
    },
    "export_records": {
        "estimated_duration_ms": 5000,
        "requires_confirmation": False,
        "required_inputs": ["form_id"],
        "produced_outputs": ["export_file_path", "export_count"],
        "side_effects": ["create_file"],
    },
    "search_forms": {
        "estimated_duration_ms": 500,
        "requires_confirmation": False,
        "required_inputs": [],
        "produced_outputs": ["form_list", "form_count"],
        "side_effects": [],
    },
    "search_records": {
        "estimated_duration_ms": 1000,
        "requires_confirmation": False,
        "required_inputs": ["form_id"],
        "produced_outputs": ["records_list", "record_count"],
        "side_effects": [],
    },
    "inventory_queries": {
        "estimated_duration_ms": 1500,
        "requires_confirmation": False,
        "required_inputs": [],
        "produced_outputs": ["inventory_result", "low_stock_items", "total_value"],
        "side_effects": [],
    },
    "sales_queries": {
        "estimated_duration_ms": 1500,
        "requires_confirmation": False,
        "required_inputs": [],
        "produced_outputs": ["sales_result", "sales_count", "total_revenue"],
        "side_effects": [],
    },
    "analyze_document": {
        "estimated_duration_ms": 8000,
        "requires_confirmation": False,
        "required_inputs": ["file_path"],
        "produced_outputs": ["analysis_result", "detected_fields"],
        "side_effects": [],
    },
    "generate_statistics": {
        "estimated_duration_ms": 3000,
        "requires_confirmation": False,
        "required_inputs": ["form_id"],
        "produced_outputs": ["statistics_result", "charts_data"],
        "side_effects": [],
    },
    "search_fields": {
        "estimated_duration_ms": 500,
        "requires_confirmation": False,
        "required_inputs": ["form_id"],
        "produced_outputs": ["fields_list", "field_count"],
        "side_effects": [],
    },
}

# ═══════════════════════════════════════════════════════════════════
# Plan decomposition patterns
# ═══════════════════════════════════════════════════════════════════

# pattern_name -> (triggers keywords, [step_spec])
_PLAN_PATTERNS: list[dict[str, Any]] = [
    {
        "name": "import_then_query",
        "triggers": ["import", "cargar", "subir", "excel", "crear form", "nuevo form"],
        "steps": [
            {"tool": "create_form", "description": "Crear formulario", "produces": ["form_id"], "optional": True},
            {"tool": "import_records", "description": "Importar registros", "requires": ["form_id"], "produces": ["import_summary"]},
        ],
    },
    {
        "name": "query_then_analyze",
        "triggers": ["analiza", "investiga", "busca.*y.*muestra", "cuantos.*y.*dime"],
        "steps": [
            {"tool": "search_records", "description": "Buscar registros", "produces": ["records_list"]},
            {"tool": "generate_statistics", "description": "Generar estadisticas", "requires": ["records_list"]},
        ],
    },
    {
        "name": "create_then_import",
        "triggers": ["crea.*form.*y.*import", "nuevo.*form.*y.*carg"],
        "steps": [
            {"tool": "create_form", "description": "Crear formulario", "produces": ["form_id"]},
            {"tool": "import_records", "description": "Importar datos", "requires": ["form_id"], "produces": ["import_summary"]},
        ],
    },
    {
        "name": "import_then_inventory",
        "triggers": ["import.*y.*stock", "carg.*y.*inventario", "carg.*y.*bajo stock", "import.*stock", "import.*bajo"],
        "steps": [
            {"tool": "create_form", "description": "Crear formulario (si necesario)", "produces": ["form_id"], "optional": True},
            {"tool": "import_records", "description": "Importar registros", "requires": ["form_id"], "produces": ["import_summary"]},
            {"tool": "inventory_queries", "description": "Consultar inventario", "produces": ["inventory_result"]},
        ],
    },
    {
        "name": "import_then_sales",
        "triggers": ["import.*y.*venta", "carg.*y.*venta", "import.*venta"],
        "steps": [
            {"tool": "create_form", "description": "Crear formulario (si necesario)", "produces": ["form_id"], "optional": True},
            {"tool": "import_records", "description": "Importar registros", "requires": ["form_id"], "produces": ["import_summary"]},
            {"tool": "sales_queries", "description": "Consultar ventas", "produces": ["sales_result"]},
        ],
    },
    {
        "name": "analyze_then_create",
        "triggers": ["analiza.*doc.*y.*crea.*form", "doc.*y.*crea", "excel.*y.*crea"],
        "steps": [
            {"tool": "analyze_document", "description": "Analizar documento", "produces": ["analysis_result"]},
            {"tool": "create_form", "description": "Crear formulario desde analisis", "requires": ["analysis_result"], "produces": ["form_id"]},
        ],
    },
    {
        "name": "full_import_workflow",
        "triggers": ["form.*import.*low.*stock", "completo", "todo.*import", "flujo.*completo"],
        "steps": [
            {"tool": "search_forms", "description": "Verificar formularios existentes", "produces": ["form_list"]},
            {"tool": "create_form", "description": "Crear formulario si no existe", "requires": ["form_list"], "produces": ["form_id"], "optional": True},
            {"tool": "import_records", "description": "Importar registros", "requires": ["form_id"], "produces": ["import_summary"]},
            {"tool": "inventory_queries", "description": "Consultar inventario", "produces": ["inventory_result"]},
        ],
    },
]

# ═══════════════════════════════════════════════════════════════════
# TaskPlanner
# ═══════════════════════════════════════════════════════════════════


class TaskPlanner:
    """
    Analyzes a user request and decomposes it into ordered, dependency-resolved steps.

    Responsibilities:
      - Analyse the user question + ChatIntent
      - Match against known multi-step patterns
      - Resolve required tools for each step
      - Validate dependencies (required_inputs <= produced_outputs from prior steps)
      - Build the Plan
    """

    def __init__(self):
        from apps.platform.ai.services.tools.registry import ToolRegistry
        self.registry = ToolRegistry.get_instance()
        self.registry.discover()

    def create_plan(self, question: str, intent: ChatIntent, extra_context: dict | None = None) -> Plan:
        """
        Create a Plan from a user question and ChatIntent.

        1. Check if the question matches any multi-step pattern
        2. If yes, expand into ordered steps with dependency resolution
        3. If no, create a single-step plan
        4. Validate all dependencies
        """
        plan = Plan(question=question, context=extra_context or {})

        matched_pattern = self._match_pattern(question, intent)
        if matched_pattern:
            step_specs = matched_pattern["steps"]
            plan_step_specs = []
            for spec in step_specs:
                plan_step_specs.append(spec)
            self._expand_steps(plan, plan_step_specs, question, intent)
            plan.metrics["pattern"] = matched_pattern["name"]
        else:
            # Single step — resolve tool from intent
            self._make_single_step(plan, question, intent)

        self._validate_dependencies(plan)
        self._mark_ready_steps(plan)

        # Estimate total duration
        total_est = 0
        for step in plan.steps:
            meta = _TOOL_METADATA.get(step.tool_name, {})
            total_est += meta.get("estimated_duration_ms", 1000)
        plan.metrics["estimated_duration_ms"] = total_est
        plan.metrics["step_count"] = len(plan.steps)

        logger.info(
            "Plan created: id=%s steps=%d pattern=%s estimated=%dms",
            plan.id, len(plan.steps),
            plan.metrics.get("pattern", "single"),
            total_est,
        )
        return plan

    def _match_pattern(self, question: str, intent: ChatIntent) -> dict | None:
        """Match a question against known multi-step patterns."""
        q_lower = question.lower()

        # Check for "import ... and ... low stock" type combined intents
        import_signals = any(k in q_lower for k in ["import", "cargar", "subir", "excel"])
        stock_signals = any(k in q_lower for k in ["stock", "inventario", "bajo"])
        sales_signals = any(k in q_lower for k in ["venta", "vendido"])
        create_signals = any(k in q_lower for k in ["crea", "nuevo form", "nuevo formulario"])
        analyze_signals = any(k in q_lower for k in ["analiza", "documento", "doc"])
        query_signals = any(k in q_lower for k in ["muestra", "busca", "cuanto", "lista"])
        form_signals = any(k in q_lower for k in ["formulario", "form"])

        # Direct pattern matching
        if import_signals and stock_signals:
            return self._find_named_pattern("import_then_inventory")
        if import_signals and sales_signals:
            return self._find_named_pattern("import_then_sales")
        if create_signals and import_signals:
            return self._find_named_pattern("create_then_import")
        if import_signals and query_signals and form_signals:
            return self._find_named_pattern("full_import_workflow")
        if import_signals and query_signals:
            return self._find_named_pattern("import_then_query")
        if analyze_signals and create_signals:
            return self._find_named_pattern("analyze_then_create")
        if (import_signals or form_signals) and query_signals:
            return self._find_named_pattern("import_then_query")

        # Fallback: try keyword matching against all patterns
        for pattern in _PLAN_PATTERNS:
            triggers = pattern["triggers"]
            if any(t in q_lower for t in triggers):
                # Check more than one trigger matches
                matches = sum(1 for t in triggers if t in q_lower)
                if matches >= 2:
                    return pattern

        return None

    def _find_named_pattern(self, name: str) -> dict | None:
        for p in _PLAN_PATTERNS:
            if p["name"] == name:
                return p
        return None

    def _expand_steps(self, plan: Plan, step_specs: list[dict], question: str, intent: ChatIntent) -> None:
        """Expand step specifications into PlanSteps with dependency resolution."""
        shared_form_alias = intent.form_alias or self._guess_form_alias(question)

        # Track all produced keys from prior steps
        all_produced: set[str] = set(plan.context.keys())

        for i, spec in enumerate(step_specs):
            step_num = i + 1
            tool_name = spec["tool"]
            description = spec.get("description", tool_name)
            produces = spec.get("produces", [])
            requires = spec.get("requires", [])
            optional = spec.get("optional", False)

            params: dict[str, Any] = {}
            if shared_form_alias:
                params["form_alias"] = shared_form_alias
                params["form_filter"] = shared_form_alias

            # Copy intent params
            if intent.params:
                params.update(intent.params)

            # Infer file_path for import if extra_context has it
            if tool_name == "import_records" and plan.context.get("file_path"):
                params["file_path"] = plan.context["file_path"]

            # For import, set default mode
            if tool_name == "import_records" and "modo" not in params:
                params["modo"] = "crear"

            depends_on = [k for k in requires if k in all_produced]

            step = PlanStep(
                step_num=step_num,
                tool_name=tool_name,
                description=description,
                params=params,
                depends_on=depends_on,
                produces=produces,
            )

            plan.steps.append(step)
            all_produced.update(produces)

    def _make_single_step(self, plan: Plan, question: str, intent: ChatIntent) -> None:
        """Create a single-step plan from a ChatIntent."""
        tool = self.registry.find_tool(intent)
        if tool is None:
            # Try by intent type
            tool = self._resolve_tool_by_intent(intent)

        tool_name = tool.name if tool else "unknown"
        params: dict[str, Any] = {}
        if intent.form_alias:
            params["form_alias"] = intent.form_alias
            params["form_filter"] = intent.form_alias
        if intent.params:
            params.update(intent.params)

        step = PlanStep(
            step_num=1,
            tool_name=tool_name,
            description=f"Ejecutar {tool_name}",
            params=params,
            status=StepStatus.READY,
        )
        plan.steps.append(step)

    def _resolve_tool_by_intent(self, intent: ChatIntent):
        """Fallback tool resolution by intent type."""
        from apps.platform.ai.services.tools.registry import ToolRegistry
        mapping = {
            "data_query": "search_records",
            "document_question": "analyze_document",
            "form_creation": "create_form",
        }
        tool_name = mapping.get(intent.intent_type)
        if tool_name:
            return ToolRegistry.get_instance().get_tool(tool_name)
        return None

    def _guess_form_alias(self, question: str) -> str:
        """Guess form alias from question keywords."""
        q = question.lower()
        if "producto" in q:
            return "producto"
        if "venta" in q or "vendido" in q:
            return "venta"
        if "cliente" in q:
            return "cliente"
        if "inventario" in q or "stock" in q or "movimiento" in q:
            return "inventario"
        return ""

    def _validate_dependencies(self, plan: Plan) -> None:
        """Validate that each step's required inputs are produced by earlier steps."""
        produced_keys: set[str] = set(plan.context.keys())

        for step in plan.steps:
            missing = [k for k in step.depends_on if k not in produced_keys]
            if missing:
                logger.warning(
                    "Plan %s step %d missing dependencies: %s",
                    plan.id, step.step_num, missing,
                )
                step.status = StepStatus.FAILED
                step.error_message = f"Dependencias faltantes: {', '.join(missing)}"
            produced_keys.update(step.produces)

    def _mark_ready_steps(self, plan: Plan) -> None:
        """Mark initial steps as READY if their dependencies are satisfied."""
        resolved_keys: set[str] = set(plan.context.keys())

        for step in plan.steps:
            if step.status == StepStatus.FAILED:
                continue
            deps_met = all(k in resolved_keys for k in step.depends_on)
            if deps_met and step.status == StepStatus.PENDING:
                step.status = StepStatus.READY
            resolved_keys.update(step.produces)

    def list_available_patterns(self) -> list[dict]:
        """List all available plan patterns with their trigger keywords."""
        return [
            {
                "name": p["name"],
                "triggers": p["triggers"],
                "steps": [s["tool"] for s in p["steps"]],
            }
            for p in _PLAN_PATTERNS
        ]
