"""
Wrappers para adaptar registros de formularios dinamicos a la interfaz
que esperan los templates legacy.

Cada wrapper expone atributos con los mismos nombres que usaban los
modelos Django originales (Producto, Categoria, Venta, Cliente),
pero obtiene los datos desde ValorCampo.

Uso:

    registro = Registro.objects.get(id=1)
    producto = DynamicProductWrapper(registro, valores)
    # Ahora se puede usar: producto.nombre, producto.precio, etc.

    # Para listados:
    productos = [DynamicProductWrapper(r, valores_map[r.id])
                 for r in registros]
"""

from decimal import Decimal, InvalidOperation
from types import SimpleNamespace


def _decimal(valor, default=Decimal('0')):
    """Convierte un string a Decimal de forma segura."""
    try:
        return Decimal(str(valor).replace(',', '.'))
    except (ValueError, TypeError, InvalidOperation):
        return default


def _entero(valor, default=0):
    """Convierte un string a entero de forma segura."""
    try:
        return int(float(str(valor).replace(',', '.')))
    except (ValueError, TypeError):
        return default


# ======================================================================
# WRAPPER DE PRODUCTO
# ======================================================================


class DynamicProductWrapper:
    """
    Wrapper que emula la interfaz del modelo legacy Producto,
    extrayendo datos desde un Registro + valores de formulario dinamico.

    Los templates legacy acceden a:
        producto.nombre
        producto.precio
        producto.stock
        producto.talla
        producto.color
        producto.categoria.nombre   <- categoria es el valor plano del campo lista
        producto.imagen_final_url
        producto.total_vendidos     <- para el dashboard (se setea externamente)
        producto.valor_stock        <- para inventario (precio * stock)
    """

    def __init__(self, registro, valores):
        """
        Args:
            registro: Instancia de Registro del formulario Productos.
            valores: Dict {nombre_campo: valor_string} del registro.
        """
        self._registro = registro
        self._valores = valores or {}
        self.id = registro.id

        # Atributos calculados desde valores
        self.nombre = self._valores.get('nombre', '')
        self.precio = _decimal(self._valores.get('precio', '0'))
        self.stock = _entero(self._valores.get('stock', '0'))
        self.talla = self._valores.get('talla', '')
        self.color = self._valores.get('color', '')
        self.sku = self._valores.get('sku', '')
        self.descripcion = self._valores.get('descripcion', '')
        self.stock_minimo = _entero(self._valores.get('stock_minimo', '5'))
        self.imagen_url = self._valores.get('imagen_url', '')

        # Imagen subida
        self.imagen_nombre = self._valores.get('imagen', '')
        self.tiene_imagen_subida = bool(self.imagen_nombre)

        # Categoria: en dynamic_forms es un campo lista con el nombre plano
        categoria_val = self._valores.get('categoria', '').strip()
        self.categoria = SimpleNamespace(
            nombre=categoria_val or 'Sin categoria',
            id=0
        )
        self.categoria_nombre = self.categoria.nombre

        # Atributos que se setean externamente (total_vendidos, valor_stock)
        self.total_vendidos = 0
        self.valor_stock = self.precio * self.stock

    @property
    def valores(self):
        """
        Expone el dict interno de valores del wrapper.

        Permite que los templates accedan a valores por nombre de campo
        sin realizar consultas adicionales a ValorCampo.

        Uso en template (Phase 2+):
            {% load dynamic_forms_extras %}
            {{ producto.valores|dict_key:"nombre" }}
        """
        return self._valores

    @property
    def imagen_final_url(self):
        """Compatibilidad con templates: prefiere URL externa sobre imagen subida."""
        if self.imagen_url:
            return self.imagen_url
        if self.imagen_nombre:
            from django.conf import settings
            return f'{settings.MEDIA_URL}dynamic_uploads/{self.imagen_nombre}'
        return ''

    @property
    def tiene_imagen(self):
        """Compatibilidad con templates legacy."""
        return bool(self.imagen_final_url)

    def __str__(self):
        return self.nombre


# ======================================================================
# WRAPPER DE VENTA
# ======================================================================


# ======================================================================
# MAPAS DE TIPOS Y MOTIVOS (compatibilidad con templates legacy)
# ======================================================================
# El modelo legacy MovimientoInventario almacena valores como
# 'entrada'/'salida'/'correccion' y 'venta_sistema'/'compra_proveedor'/etc.
# El formulario dinámico almacena valores como 'Entrada'/'Salida'/'Correccion'
# y 'Venta del sistema'/'Compra a proveedor'/etc.

_TIPO_MAP = {
    'Entrada': 'entrada',
    'Salida': 'salida',
    'Correccion': 'correccion',
}

_TIPO_DISPLAY = {
    'entrada': 'Entrada',
    'salida': 'Salida',
    'correccion': 'Correccion de stock',
}

# Los motivos en el formulario dinámico ya se almacenan como texto
# legible (ej: 'Venta del sistema'), que coincide con el display
# del modelo legacy. No requieren mapeo inverso.


# ======================================================================
# WRAPPER DE MOVIMIENTO DE INVENTARIO
# ======================================================================


class DynamicMovimientoInventarioWrapper:
    """
    Wrapper que emula la interfaz del modelo legacy MovimientoInventario,
    extrayendo datos desde un Registro + valores de formulario dinámico.

    Los templates legacy acceden a:
        movimiento.producto.nombre
        movimiento.producto.categoria.nombre
        movimiento.producto.imagen_final_url
        movimiento.tipo                  -> 'entrada', 'salida', 'correccion'
        movimiento.get_tipo_display()    -> 'Entrada', 'Correccion de stock'
        movimiento.cantidad
        movimiento.motivo
        movimiento.get_motivo_display()
        movimiento.stock_anterior
        movimiento.stock_nuevo
        movimiento.observacion
        movimiento.fecha                 -> datetime (usado con filtro |date)
    """

    def __init__(self, registro, valores, producto_wrapper=None):
        """
        Args:
            registro: Instancia de Registro del formulario MovimientosInventario.
            valores: Dict {nombre_campo: valor_string} del registro.
            producto_wrapper: Opcional, DynamicProductWrapper pre-resuelto.
                              Si no se pasa, se crea un fallback con valores disponibles.
        """
        self._registro = registro
        self._valores = valores or {}
        self.id = registro.id
        self.fecha = registro.fecha_creacion

        # --- tipo (normalizado a minúsculas para compatibilidad con templates) ---
        tipo_raw = self._valores.get('tipo', '').strip()
        self.tipo = _TIPO_MAP.get(tipo_raw, tipo_raw.lower() if tipo_raw else '')

        # --- cantidad ---
        self.cantidad = _entero(self._valores.get('cantidad', '0'))

        # --- stock_anterior / stock_nuevo ---
        self.stock_anterior = _entero(self._valores.get('stock_anterior', '0'))
        self.stock_nuevo = _entero(self._valores.get('stock_nuevo', '0'))

        # --- motivo ---
        self.motivo = self._valores.get('motivo', '').strip() or None

        # --- observacion ---
        self.observacion = self._valores.get('observacion', '').strip() or None

        # --- producto relacionado ---
        self.producto = producto_wrapper or self._resolver_producto_fallback()

    # ------------------------------------------------------------------
    # Métodos de display (emulan get_FOO_display() del modelo legacy)
    # ------------------------------------------------------------------

    def get_tipo_display(self):
        """Retorna el texto legible del tipo de movimiento.
        Ej: 'entrada' -> 'Entrada', 'correccion' -> 'Correccion de stock'"""
        return _TIPO_DISPLAY.get(self.tipo, self.tipo.capitalize() if self.tipo else '')

    def get_motivo_display(self):
        """Retorna el texto legible del motivo.
        En el formulario dinámico, el motivo ya se almacena como
        texto legible (ej: 'Venta del sistema'), por lo que
        se retorna directamente."""
        return self.motivo or ''

    # ------------------------------------------------------------------
    # Fallback cuando no se pasa producto_wrapper
    # ------------------------------------------------------------------

    def _resolver_producto_fallback(self):
        """Crea un producto fallback con los datos disponibles en valores.
        Evita errores en templates cuando no se precargaron wrappers."""
        prod_nombre = self._valores.get('producto_nombre', '')
        prod_categoria = self._valores.get('producto_categoria', '')
        prod_imagen = self._valores.get('producto_imagen', '')

        return SimpleNamespace(
            nombre=prod_nombre or f'Producto #{self._valores.get("producto", "?")}',
            categoria=SimpleNamespace(
                nombre=prod_categoria or 'Sin categoría'
            ),
            imagen_final_url=prod_imagen or '',
            tiene_imagen=bool(prod_imagen),
        )

    def __str__(self):
        return f'{self.get_tipo_display()} - {self.cantidad}'


class DynamicVentaWrapper:
    """
    Wrapper que emula la interfaz del modelo legacy Venta.

    Los templates legacy acceden a:
        venta.id
        venta.fecha
        venta.cantidad
        venta.total
        venta.producto.nombre
        venta.producto.categoria.nombre
        venta.producto.color
        venta.producto.talla
        venta.vendedor.username
        venta.cliente.nombre_completo
        venta.cliente.documento
        venta.cliente.correo
    """

    def __init__(self, registro, valores, producto_wrapper=None, cliente_wrapper=None,
                 vendedor_username=''):
        self._registro = registro
        self._valores = valores or {}
        self.id = registro.id
        self.fecha = registro.fecha_creacion

        self.cantidad = _entero(self._valores.get('cantidad', '0'))
        self.total = _decimal(self._valores.get('total', '0'))

        # Producto relacionado
        self.producto = producto_wrapper or self._resolver_producto_por_defecto()

    def _resolver_producto_por_defecto(self):
        """Crea un producto fallback con todos los atributos que esperan los templates."""
        prod_nombre = self._valores.get('producto_nombre', self._valores.get('producto', ''))
        return SimpleNamespace(
            nombre=prod_nombre,
            categoria=SimpleNamespace(nombre=''),
            color=self._valores.get('producto_color', ''),
            talla=self._valores.get('producto_talla', ''),
            imagen_final_url='',
            tiene_imagen=False,
        )

        # Vendedor
        self.vendedor = SimpleNamespace(
            username=vendedor_username or f'#{registro.usuario_id or 0}'
        )

        # Cliente relacionado
        cliente_nombre = ''
        if cliente_wrapper:
            cliente_nombre = getattr(cliente_wrapper, 'nombre_completo', '')
        self.cliente = cliente_wrapper or SimpleNamespace(
            nombre_completo=cliente_nombre,
            documento=self._valores.get('cliente_documento', ''),
            correo=self._valores.get('cliente_correo', ''),
        )

    def __str__(self):
        return f'Venta #{self.id}'


# ======================================================================
# WRAPPER DE CLIENTE
# ======================================================================


class DynamicClienteWrapper:
    """
    Wrapper que emula la interfaz del modelo legacy Cliente.

    Los templates legacy acceden a:
        cliente.documento
        cliente.nombre
        cliente.apellido
        cliente.nombre_completo
        cliente.correo
        cliente.telefono
        cliente.cantidad_ventas
        cliente.total_comprado
        cliente.ultima_compra
    """

    def __init__(self, registro, valores):
        self._registro = registro
        self._valores = valores or {}
        self.id = registro.id

        self.documento = self._valores.get('documento', '')
        self.nombre = self._valores.get('nombre', '')
        self.apellido = self._valores.get('apellido', '')
        self.correo = self._valores.get('correo', '')
        self.telefono = self._valores.get('telefono', '')
        self.direccion = self._valores.get('direccion', '')

        self.cantidad_ventas = 0  # Se setea externamente
        self.total_comprado = Decimal('0')
        self.ultima_compra = None

    @property
    def fecha_registro(self):
        """Compatibilidad con templates legacy."""
        return self._registro.fecha_creacion

    @property
    def nombre_completo(self):
        return f'{self.nombre} {self.apellido}'.strip()

    @property
    def activo(self):
        return self._valores.get('activo', 'Sí') == 'Sí'

    def __str__(self):
        return f'{self.nombre_completo} - {self.documento}'
