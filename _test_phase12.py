import sys, os, json
sys.path.insert(0, os.getcwd())
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings.base'
import django
django.setup()

from apps.platform.ai.services.planner import TaskPlanner, Plan, PlanStep, StepStatus
from apps.platform.ai.services.decision_engine import ChatIntent

print("=== 1. TaskPlanner: create_plan single-step ===")
planner = TaskPlanner()
intent = ChatIntent(
    intent_type="data_query",
    sub_intent="count",
    target_model="formulario",
    form_alias="producto",
    explanation="cuantos productos hay",
    confidence=0.9,
)
plan = planner.create_plan("cuantos productos hay", intent)
print(f"Plan: id={plan.id}, steps={len(plan.steps)}, status={plan.status}")
for s in plan.steps:
    print(f"  Step {s.step_num}: {s.tool_name} — {s.description} [{s.status.value}]")
print(f"Metrics: {json.dumps(plan.metrics, indent=2)}")

print("\n=== 2. TaskPlanner: create_plan multi-step (import + stock) ===")
intent2 = ChatIntent(
    intent_type="general_chat",
    form_alias="producto",
    explanation="import this excel and show me low stock",
    confidence=0.5,
)
plan2 = planner.create_plan("Quiero importar este excel y ver el stock bajo", intent2)
print(f"Plan: id={plan2.id}, steps={len(plan2.steps)}, status={plan2.status}")
for s in plan2.steps:
    print(f"  Step {s.step_num}: {s.tool_name} — {s.description} [{s.status.value}] deps={s.depends_on} prods={s.produces}")
print(f"Metrics: {json.dumps(plan2.metrics, indent=2)}")

print("\n=== 3. TaskPlanner: create_plan multi-step (form + import) ===")
intent3 = ChatIntent(
    intent_type="form_creation",
    explanation="crea un nuevo formulario y luego importa los datos",
    confidence=0.6,
)
plan3 = planner.create_plan("Crea un nuevo formulario y luego importa los datos", intent3)
print(f"Plan: id={plan3.id}, steps={len(plan3.steps)}, status={plan3.status}")
for s in plan3.steps:
    print(f"  Step {s.step_num}: {s.tool_name} — {s.description} [{s.status.value}] deps={s.depends_on} prods={s.produces}")

print("\n=== 4. PlanStep serialization ===")
step = PlanStep(step_num=1, tool_name="test_tool", description="Test step")
d = step.to_dict()
print(f"to_dict: {json.dumps(d, indent=2)}")
assert d["step_num"] == 1
assert d["tool_name"] == "test_tool"
assert d["status"] == "pending"
print("Step serialization OK")

print("\n=== 5. Plan serialization ===")
p = Plan(question="test question")
p.steps.append(step)
p.status = "ready"
d = p.to_dict()
print(f"Plan to_dict keys: {list(d.keys())}")
assert d["status"] == "ready"
assert d["question"] == "test question"
assert len(d["steps"]) == 1
print("Plan serialization OK")

print("\n=== 6. SmartLearner plan stats ===")
from apps.platform.ai.services.smart_learner import SmartLearner
sl = SmartLearner()
sl.record_plan(
    plan_id="test-1", question="test import",
    pattern="import_then_inventory", step_count=3,
    success=True, total_duration_ms=15000.0,
    completed_steps=3, failed_steps=0,
    tool_sequence=["create_form", "import_records", "inventory_queries"],
)
sl.record_plan(
    plan_id="test-2", question="test form create",
    pattern="create_then_import", step_count=2,
    success=False, total_duration_ms=5000.0,
    completed_steps=1, failed_steps=1,
    tool_sequence=["create_form", "import_records"],
    error_message="Import failed",
)
stats = sl.get_plan_stats()
print(f"Plan stats: total={stats['total_plans']}, success_rate={stats['success_rate']}%")
print(f"  avg_steps={stats['avg_steps']}, avg_duration={stats['avg_duration_ms']}ms")
print(f"  patterns={json.dumps(stats['common_patterns'])}")
print(f"  top_tools={json.dumps(stats['most_used_tools'])}")

print("\n=== ALL TESTS PASSED ===")
