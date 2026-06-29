"""
Phase 2: Runtime instrumentation of IncludeNode + ExtendsNode.
Simulates the exact view state: session with di_pipeline_result.
"""
import os, sys, logging, json

os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.base"
import django
django.setup()

logging.basicConfig(level=logging.INFO, force=True)
logger = logging.getLogger("diag")

# ── STEP 1: Monkey patch INCLUDE node ──
from django.template.loader_tags import IncludeNode, ExtendsNode

_include_depth = [0]
_include_stack = []
_orig_include = IncludeNode.render

def patched_include(self, context):
    tname = str(getattr(self, 'template', getattr(self, 'name', '?')))
    _include_depth[0] += 1
    _include_stack.append(tname)
    
    indent = "  " * _include_depth[0]
    logger.info("%s[DEPTH %d] INCLUDE → %s", indent, _include_depth[0], tname)
    
    if _include_depth[0] > 20:
        logger.error("=" * 70)
        logger.error("RECURSION DETECTED in IncludeNode!")
        for i, n in enumerate(_include_stack):
            logger.error("  %d: %s", i, n)
        logger.error("=" * 70)
        _include_depth[0] -= 1
        _include_stack.pop()
        return ""
    
    try:
        return _orig_include(self, context)
    finally:
        _include_depth[0] -= 1
        _include_stack.pop()

IncludeNode.render = patched_include

# ── STEP 2: Monkey patch EXTENDS node ──
_extend_stack = []
_orig_extend = ExtendsNode.render

def patched_extend(self, context):
    # Resolve parent name
    parent_name = getattr(self, 'parent_name', None)
    if parent_name is not None:
        try:
            resolved = parent_name.resolve(context)
        except Exception:
            resolved = str(parent_name)
    else:
        resolved = "?"
    
    logger.info("  [EXTENDS] → %s", resolved)
    return _orig_extend(self, context)

ExtendsNode.render = patched_extend

# ── STEP 3: Simulate the GET request with session data ──
# Create mock session data like what would exist after a POST/analyze
# Fix ALLOWED_HOSTS for test
from django.conf import settings
settings.ALLOWED_HOSTS = ["*"]

from django.test import Client
from django.contrib.auth.models import User

user, created = User.objects.get_or_create(username="test_diag2", defaults={"is_superuser": True})
if created:
    user.set_password("test123")
    user.save()
else:
    user.is_superuser = True
    user.save()
from django.contrib.auth.models import Group
admin_group, _ = Group.objects.get_or_create(name="Administrador")
user.groups.add(admin_group)

client = Client(HTTP_HOST="testserver")
client.force_login(user)

# ── STEP 4: Make the GET request ──
logger.info("=" * 70)
logger.info("REQUEST: GET /document-intelligence/upload/ (WITH session data)")
logger.info("=" * 70)

# First, we need session data. Let's set it via the client's session
session = client.session
session["di_pipeline_result"] = {
    "form_name": "Productos",
    "form_description": "Productos importados",
    "fields": [
        {"name": "Nombre", "type": "texto", "required": True, "is_identifier": True, "order": 0},
        {"name": "Precio", "type": "moneda", "required": True, "order": 1},
        {"name": "Cantidad", "type": "numero", "required": True, "order": 2},
    ],
    "classification": "Productos",
    "quality": {
        "stars": 4,
        "label": "Buena",
        "strengths": ["Campos detectados"],
        "risks": [],
        "recommendations": ["Revisar nombres"],
    },
    "similar_forms": [
        {"id": 1, "nombre": "Productos", "similitud": 85, "campos_coincidentes": 5,
         "campos_nuevos": 2, "total_campos": 7, "campos_propuestos": ["Nombre", "Precio"]}
    ],
}
session["di_catalog_suggestions"] = []
session.save()

logger.info("Session data set with di_pipeline_result")

try:
    response = client.get("/document-intelligence/upload/", follow=True)
    logger.info("RESPONSE STATUS: %d", response.status_code)
    logger.info("RESPONSE LENGTH: %d bytes", len(response.content))
except RecursionError as e:
    logger.error("RECURSIONERROR: %s", e)
except Exception as e:
    logger.error("EXCEPTION: %s: %s", type(e).__name__, e)

logger.info("=" * 70)
logger.info("REQUEST: GET /document-intelligence/upload/ (WITHOUT session data)")
logger.info("=" * 70)

# Clear session
session["di_pipeline_result"] = None
session.save()

try:
    response = client.get("/document-intelligence/upload/", follow=True)
    logger.info("RESPONSE STATUS: %d", response.status_code)
    logger.info("RESPONSE LENGTH: %d bytes", len(response.content))
except RecursionError as e:
    logger.error("RECURSIONERROR: %s", e)
except Exception as e:
    logger.error("EXCEPTION: %s: %s", type(e).__name__, e)
