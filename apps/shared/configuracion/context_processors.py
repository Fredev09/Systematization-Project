from django.db.utils import OperationalError, ProgrammingError

from config.permissions import es_administrador, rol_usuario
from .models import ConfiguracionTienda


CONFIGURACION_DEFECTO = {
    'nombre_tienda': 'Tonjeo',
    'telefono': '',
    'direccion': '',
    'correo': '',
    'stock_minimo_alerta': 5,
    'tema_defecto': 'dark',
    'mostrar_agotados_catalogo': True,
}


def configuracion_tienda(request):
    try:
        configuracion = ConfiguracionTienda.obtener()
    except (OperationalError, ProgrammingError):
        configuracion = CONFIGURACION_DEFECTO

    user = getattr(request, 'user', None)

    return {
        'configuracion_tienda': configuracion,
        'stock_minimo_alerta': getattr(configuracion, 'stock_minimo_alerta', CONFIGURACION_DEFECTO['stock_minimo_alerta']),
        'es_admin': es_administrador(user) if user and user.is_authenticated else False,
        'rol_usuario': rol_usuario(user) if user and user.is_authenticated else '',
    }
