# BACKEND ES LA APP PRINCIPAL (DASHBOARD)

from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.shortcuts import redirect, render

from config.pagination import OPCIONES_POR_PAGINA, obtener_por_pagina, parametros_sin_pagina
from apps.legacy.productos.models import Producto
from apps.legacy.ventas.models import Venta
from apps.shared.configuracion.models import ConfiguracionTienda
from .permissions import es_administrador, rol_usuario


def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        remember = request.POST.get('remember')

        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)

            if remember:
                request.session.set_expiry(1209600)
            else:
                request.session.set_expiry(0)

            return redirect('dashboard')
        else:
            messages.error(request, 'Usuario o contraseña incorrectos')

    return render(request, 'public/login.html')


@login_required(login_url='login')
def dashboard(request):
    query = request.GET.get('q', '').strip()
    es_admin = es_administrador(request.user)
    configuracion = ConfiguracionTienda.obtener()
    stock_minimo = configuracion.stock_minimo_alerta

    productos = Producto.objects.select_related('categoria').all()

    if query:
        productos = productos.filter(
            Q(nombre__icontains=query) |
            Q(categoria__nombre__icontains=query) |
            Q(color__icontains=query) |
            Q(talla__icontains=query)
        )

    productos = productos.annotate(
        total_vendidos=Sum('ventas__cantidad')
    ).distinct().order_by('-total_vendidos', 'nombre')[:3]

    total_productos = Producto.objects.count()
    stock_bajo = Producto.objects.filter(stock__gte=1, stock__lte=stock_minimo).count()

    if es_admin:
        ventas_base = Venta.objects.select_related('producto', 'vendedor')
        total_clientes = User.objects.count()
    else:
        ventas_base = Venta.objects.select_related('producto', 'vendedor').filter(
            vendedor=request.user
        )
        total_clientes = None

    total_ventas = ventas_base.aggregate(total=Sum('total'))['total'] or 0

    ventas_recientes = ventas_base.order_by('-fecha')[:5]

    return render(request, 'dashboard/dashboard.html', {
        'query': query,
        'productos': productos,
        'ventas_recientes': ventas_recientes,
        'total_productos': total_productos,
        'stock_bajo': stock_bajo,
        'stock_minimo_alerta': stock_minimo,
        'total_ventas': total_ventas,
        'total_clientes': total_clientes,
        'es_admin': es_admin,
        'rol_usuario': rol_usuario(request.user),
    })


@login_required(login_url='login')
def usuarios(request):
    if not es_administrador(request.user):
        messages.error(request, 'No tienes permisos para ver usuarios.')
        return redirect('dashboard')

    usuarios = User.objects.all().order_by('-date_joined')

    total_usuarios = usuarios.count()
    usuarios_activos = usuarios.filter(is_active=True).count()
    usuarios_inactivos = usuarios.filter(is_active=False).count()

    per_page, per_page_int = obtener_por_pagina(request)
    paginator = Paginator(usuarios, per_page_int)
    pagina = request.GET.get('page')
    usuarios_pagina = paginator.get_page(pagina)
    query_params = parametros_sin_pagina(request, ['page'])

    return render(request, 'usuarios/usuarios.html', {
        'usuarios': usuarios_pagina,
        'total_usuarios': total_usuarios,
        'usuarios_activos': usuarios_activos,
        'usuarios_inactivos': usuarios_inactivos,
        'es_admin': es_administrador(request.user),
        'rol_usuario': rol_usuario(request.user),
        'query_params': query_params,
        'per_page': per_page,
        'per_page_options': OPCIONES_POR_PAGINA,
    })

def inicio(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    return redirect('login')


def formulario(request):
    return render(request, 'formularios/formulario.html')


def index(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    return redirect('login')
