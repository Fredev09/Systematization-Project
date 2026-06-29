"""
Phase 4: Investigate recursive CONTEXT objects, NOT template includes.
Monkeypatches render() to print and analyze every context value before rendering.
Detects cyclic references, self-referencing objects, and problematic __str__/properties.
"""
import os, sys, gc, logging, json, pprint
from collections import defaultdict
from types import MethodType

os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.base"
import django
django.setup()

from django.conf import settings
settings.ALLOWED_HOSTS = ["*"]
settings.STATICFILES_DIRS = []

logging.basicConfig(level=logging.INFO, force=True)
logger = logging.getLogger("diag")

# ── Track visited ids for cycle detection ──
_seen_ids = set()

def find_cycles(obj, path="root", depth=0, path_ids=None):
    """Traverse object tree. path_ids = set of ids seen in THIS path.
    Uses path-specific visited set (copied per branch) to detect actual cycles."""
    if path_ids is None:
        path_ids = set()
    
    if obj is None or isinstance(obj, (str, int, float, bool, bytes, type)):
        return []
    
    obj_id = id(obj)
    if obj_id in path_ids:
        return [(path, type(obj).__name__, obj_id)]
    
    cycles = []
    if depth > 50:
        return cycles
    
    new_ids = set(path_ids)
    new_ids.add(obj_id)
    
    try:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if not isinstance(v, (str, int, float, bool, bytes, type)):
                    cycles.extend(find_cycles(v, f"{path}.{k}", depth+1, new_ids))
        
        elif isinstance(obj, (list, tuple)):
            for i, v in enumerate(obj):
                if not isinstance(v, (str, int, float, bool, bytes, type)):
                    cycles.extend(find_cycles(v, f"{path}[{i}]", depth+1, new_ids))
        
        elif hasattr(obj, '_meta') and hasattr(obj, 'pk'):
            for field in obj._meta.get_fields():
                try:
                    val = getattr(obj, field.name)
                    if val is not None and not isinstance(val, (str, int, float, bool, bytes)):
                        cycles.extend(find_cycles(val, f"{path}.{field.name}", depth+1, new_ids))
                except Exception:
                    pass
        
        elif hasattr(obj, '__dataclass_fields__'):
            for fn in obj.__dataclass_fields__:
                try:
                    val = getattr(obj, fn)
                    if val is not None and not isinstance(val, (str, int, float, bool, bytes)):
                        cycles.extend(find_cycles(val, f"{path}.{fn}", depth+1, new_ids))
                except Exception:
                    pass
        
        elif hasattr(obj, '__dict__'):
            for an in list(obj.__dict__.keys()):
                if not an.startswith('_'):
                    try:
                        val = obj.__dict__[an]
                        if val is not None and not isinstance(val, (str, int, float, bool, bytes)):
                            cycles.extend(find_cycles(val, f"{path}.{an}", depth+1, set(new_ids)))
                    except Exception:
                        pass
    except RecursionError:
        logger.error("  ⚠️  RECURSION in find_cycles at %s!", path)
        cycles.append((path, type(obj).__name__, id(obj)))
    
    return cycles


def analyze_value(name, value, depth=0, max_depth=5, path="root"):
    """Analyze a value for potential recursion sources."""
    if depth > max_depth:
        return
    
    obj_type = type(value).__name__
    obj_id = id(value)
    
    # Check for self-reference
    has_self_ref = False
    
    try:
        if isinstance(value, dict):
            for k, v in value.items():
                if id(v) == id(value):
                    has_self_ref = True
                    logger.warning("  ⚠️  SELF-REFERENCE: %s.%s references itself!", path, k)
        elif isinstance(value, (list, tuple)):
            for i, v in enumerate(value):
                if id(v) == id(value):
                    has_self_ref = True
                    logger.warning("  ⚠️  SELF-REFERENCE: %s[%d] references itself!", path, i)
    except Exception:
        pass
    
    # repr truncated
    try:
        r = repr(value)
        if len(r) > 200:
            r = r[:200] + "..."
    except Exception as e:
        r = f"<repr error: {e}>"
    
    # Check if Django model
    is_model = hasattr(value, '_meta') and hasattr(value, 'pk')
    is_qs = hasattr(value, 'model') and hasattr(value, 'query')
    is_dataclass = hasattr(value, '__dataclass_fields__')
    has_dict = hasattr(value, '__dict__') and not is_model
    
    # Check if it has __str__ or __repr__ that might recurse
    has_unsafe_str = False
    if is_model:
        cls = type(value)
        if hasattr(cls, '__str__') and cls.__str__ is not object.__str__:
            # Check if __str__ accesses related objects
            try:
                str_code = cls.__str__.__code__
                if str_code:
                    has_unsafe_str = True  # Could access related objects
            except Exception:
                pass
    
    logger.info("  %s%s = <%s at 0x%x>%s%s%s%s%s%s",
        "  " * depth,
        name,
        obj_type,
        obj_id,
        " [MODEL]" if is_model else "",
        " [QS]" if is_qs else "",
        " [DATACLASS]" if is_dataclass else "",
        " [SELF-REF]" if has_self_ref else "",
        " [len=%d]" % len(value) if isinstance(value, (list, tuple, dict)) and hasattr(value, '__len__') else "",
        " [unsafe __str__]" if has_unsafe_str else "",
    )
    logger.info("  %s  repr: %s", "  " * depth, r)
    
    # Recurse into containers
    if isinstance(value, dict) and depth < max_depth:
        for k, v in list(value.items())[:10]:
            analyze_value(str(k), v, depth+1, max_depth, f"{path}.{k}")
        if len(value) > 10:
            logger.info("  %s  ... (%d more keys)", "  " * (depth+1), len(value) - 10)
    
    elif isinstance(value, (list, tuple)) and depth < max_depth:
        for i, v in enumerate(list(value)[:5]):
            analyze_value(f"[{i}]", v, depth+1, max_depth, f"{path}[{i}]")
        if len(value) > 5:
            logger.info("  %s  ... (%d more items)", "  " * (depth+1), len(value) - 5)
    
    elif is_model and depth < max_depth:
        # Check critical fields
        for field in value._meta.get_fields():
            fname = field.name
            if not fname.startswith('_'):
                try:
                    fval = getattr(value, fname)
                    if fval is not None and not isinstance(fval, (str, int, float, bool, bytes)):
                        analyze_value(fname, fval, depth+1, max_depth, f"{path}.{fname}")
                except Exception:
                    pass


# ── Monkeypatch django.shortcuts.render ──
import django.shortcuts
_orig_render = django.shortcuts.render

def patched_render(request, template_name, context=None, *args, **kwargs):
    if context is None:
        context = {}
    
    if template_name and "document_upload" in str(template_name):
        logger.info("=" * 80)
        logger.info("RENDER INTERCEPTED: %s", template_name)
        logger.info("=" * 80)
        logger.info("Context keys: %s", list(context.keys()))
        logger.info("")
        
        for k, v in context.items():
            logger.info("--- KEY: %s ---", k)
            analyze_value(k, v)
            logger.info("")
        
        # ── Deep cycle detection ──
        logger.info("=" * 80)
        logger.info("DEEP CYCLE DETECTION (gc.get_referents)")
        logger.info("=" * 80)
        for k, v in context.items():
            cycles = find_cycles(v, k)
            if cycles:
                logger.warning("⚠️  CYCLES FOUND in %s:", k)
                for path, typename, oid in cycles:
                    logger.warning("   %s → <%s at 0x%x>", path, typename, oid)
            else:
                logger.info("  %s: NO cycles detected", k)
        
        # ── Check __str__ methods of all model instances in context ──
        logger.info("")
        logger.info("=" * 80)
        logger.info("CHECK: __str__ methods of ALL model instances")
        logger.info("=" * 80)
        def check_str(obj, path="", checked=None):
            if checked is None:
                checked = set()
            obj_id = id(obj)
            if obj_id in checked:
                return
            checked.add(obj_id)
            
            if hasattr(obj, '_meta') and hasattr(obj, 'pk'):
                try:
                    str_val = str(obj)
                    logger.info("  %s → __str__: %s", path + type(obj).__name__, str_val[:100])
                except RecursionError:
                    logger.error("  ⚠️  RECURSION IN __str__ of %s at path %s!", type(obj).__name__, path)
                except Exception as e:
                    logger.warning("  ⚠️  __str__ error for %s: %s", type(obj).__name__, e)
            
            if isinstance(obj, dict):
                for k, v in obj.items():
                    check_str(v, f"{path}.{k}", checked)
            elif isinstance(obj, (list, tuple)):
                for i, v in enumerate(obj):
                    check_str(v, f"{path}[{i}]", checked)
            elif hasattr(obj, '__dict__'):
                for attr_name in dir(obj):
                    if not attr_name.startswith('_'):
                        try:
                            val = getattr(obj, attr_name)
                            if hasattr(val, '_meta') or isinstance(val, (dict, list, tuple)):
                                check_str(val, f"{path}.{attr_name}", checked)
                        except RecursionError:
                            logger.error("  ⚠️  RECURSION accessing %s.%s!", path, attr_name)
                            break
                        except Exception:
                            pass
        
        for k, v in context.items():
            check_str(v, f"context.{k}")
    
    return _orig_render(request, template_name, context, *args, **kwargs)

django.shortcuts.render = patched_render

# ── Also patch the view's render call directly ──
from django.template import loader
_orig_loader_render = loader.render_to_string
def patched_loader_render(*args, **kwargs):
    return _orig_loader_render(*args, **kwargs)
loader.render_to_string = patched_loader_render

# ── Simulate E2E flow ──
from django.test import Client
from django.contrib.auth.models import User, Group
from django.core.files.uploadedfile import SimpleUploadedFile
import io
from openpyxl import Workbook

admin_group, _ = Group.objects.get_or_create(name="Administrador")
user, _ = User.objects.get_or_create(username="test_ctx", defaults={"is_superuser": True})
user.set_password("test123")
user.groups.add(admin_group)
user.save()

client = Client(HTTP_HOST="testserver")
client.force_login(user)

# Make POST to set session data
wb = Workbook()
ws = wb.active; ws.title = "Data"
ws.append(["Nombre", "Precio", "Cantidad"])
ws.append(["Prod A", 100, 10])
ws.append(["Prod B", 200, 20])
buf = io.BytesIO(); wb.save(buf); buf.seek(0)
xlsx = SimpleUploadedFile("test.xlsx", buf.read(),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

logger.info("")
logger.info("=" * 80)
logger.info("E2E TEST: POST + FOLLOW redirect")
logger.info("=" * 80)

try:
    resp = client.post("/document-intelligence/upload/", {
        "action": "analyze", "document_file": xlsx,
    }, follow=True)
    logger.info("FINAL STATUS: %d", resp.status_code)
    logger.info("FINAL LENGTH: %d bytes", len(resp.content))
except RecursionError as e:
    logger.error("RECURSIONERROR DURING TEST: %s", e)
    import traceback
    traceback.print_exc()
except Exception as e:
    logger.error("EXCEPTION: %s: %s", type(e).__name__, e)
