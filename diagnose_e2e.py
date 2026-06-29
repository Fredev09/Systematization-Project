"""
Phase 3: Full E2E simulation — POST upload + follow redirect to GET.
"""
import os, logging, io, sys

os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.base"
import django
django.setup()

from django.conf import settings
settings.ALLOWED_HOSTS = ["*"]
settings.STATICFILES_DIRS = []

logging.basicConfig(level=logging.INFO, force=True)
logger = logging.getLogger("diag")

# ── Patch IncludeNode to trace ALL includes ──
from django.template.loader_tags import IncludeNode, ExtendsNode

_inc_depth = [0]
_inc_stack = []
_orig_inc = IncludeNode.render

def patched_inc(self, context):
    tname = str(getattr(self, "template", getattr(self, "name", "?")))
    _inc_depth[0] += 1
    _inc_stack.append(tname)
    indent = "  " * _inc_depth[0]
    logger.info("%s[DEPTH %d] INCLUDE → %s", indent, _inc_depth[0], tname)
    if _inc_depth[0] > 50:
        logger.error("CYCLE! Stack:")
        for i, n in enumerate(_inc_stack):
            logger.error("  %d: %s", i, n)
        _inc_depth[0] -= 1
        _inc_stack.pop()
        return ""
    try:
        return _orig_inc(self, context)
    finally:
        _inc_depth[0] -= 1
        _inc_stack.pop()

IncludeNode.render = patched_inc

_ext_orig = ExtendsNode.render
def patched_ext(self, context):
    try:
        parent = self.parent_name.resolve(context)
    except Exception:
        parent = "?"
    logger.info("  [EXTENDS] → %s", parent)
    return _ext_orig(self, context)
ExtendsNode.render = patched_ext

# ── Patch make_json_serializable to track what it serializes ──
import types
from apps.platform.ai import utils as ai_utils
_orig_serialize = ai_utils.make_json_serializable
_serialize_calls = []

def patched_serialize(obj, _seen=None):
    t = type(obj).__name__
    _serialize_calls.append(t)
    if len(_serialize_calls) > 1000:
        logger.warning("make_json_serializable called %d times", len(_serialize_calls))
    return _orig_serialize(obj, _seen)

ai_utils.make_json_serializable = patched_serialize

# ── Create admin user ──
from django.contrib.auth.models import User, Group
admin_group, _ = Group.objects.get_or_create(name="Administrador")
user, _ = User.objects.get_or_create(username="test_e2e", defaults={"is_superuser": True})
user.set_password("test123")
user.groups.add(admin_group)
user.save()

from django.test import Client
client = Client(HTTP_HOST="testserver")
client.force_login(user)

# ── Make POST + follow redirect ──
from openpyxl import Workbook
wb = Workbook()
ws = wb.active; ws.title = "Data"
ws.append(["Nombre", "Precio", "Cantidad"])
ws.append(["Prod A", 100, 10])
ws.append(["Prod B", 200, 20])
buf = io.BytesIO(); wb.save(buf); buf.seek(0)

from django.core.files.uploadedfile import SimpleUploadedFile
xlsx = SimpleUploadedFile("test.xlsx", buf.read(), 
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

logger.info("=" * 70)
logger.info("STEP 1: POST /document-intelligence/upload/ (analyze)")
logger.info("=" * 70)
try:
    resp = client.post("/document-intelligence/upload/", {
        "action": "analyze", "document_file": xlsx,
    }, follow=True)
    logger.info("POST status: %d", resp.status_code)
    logger.info("POST redirect chain: %s", resp.redirect_chain)
    logger.info("POST final length: %d bytes", len(resp.content))
    
    if resp.status_code == 200:
        content = resp.content.decode("utf-8", errors="replace")
        if "RecursionError" in content or "maximum recursion" in content:
            logger.error("RECURSION IN RESPONSE!")
        elif "Editor de formulario" in content:
            logger.info("Result section rendered OK")
        elif "Suelta tu archivo" in content:
            logger.info("Empty upload form (no result)")
        else:
            logger.info("First 500 chars: %s", content[:500])
except RecursionError as e:
    logger.error("RECURSIONERROR: %s", e)
except Exception as e:
    logger.error("EXCEPTION: %s: %s", type(e).__name__, e)

# Print serialization stats
from collections import Counter
logger.info("Serialization call types: %s", dict(Counter(_serialize_calls).most_common(20)))
