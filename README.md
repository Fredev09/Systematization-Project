# Tonjeo

Tonjeo es una aplicación web desarrollada con Python y Django para la gestión comercial de un negocio de venta de ropa. El sistema permite administrar productos, categorías, inventario, ventas, usuarios y reportes, con conexión a base de datos MySQL.

## Objetivo del proyecto

Diseñar y desarrollar una aplicación funcional que permita controlar productos, ventas, aplicando el uso de Python, Django, base de datos y operaciones CRUD.

## Tecnologías utilizadas

- Python 3.x
- Django 4.2.11
- MySQL
- HTML
- CSS
- JavaScript
- Bootstrap Icons / Boxicons
- Pandas
- OpenPyXL

## Módulos principales

### Dashboard

Permite visualizar información general del sistema y acceder rápidamente a las secciones principales.

### Productos

Permite gestionar el catálogo de productos. Incluye creación, edición, eliminación, búsqueda y filtros por categoría o estado de stock.

### Inventario

Permite controlar el stock de los productos. Incluye visualización de productos disponibles, productos con stock bajo, productos sin stock y valor total del inventario.

### Ajuste de stock

Permite registrar movimientos de inventario mediante entradas, salidas o correcciones de stock. Cada ajuste guarda un historial con el producto, tipo de movimiento, motivo, cantidad, stock anterior, stock nuevo, observación y fecha.

### Ventas

Permite registrar ventas de productos, descontando automáticamente la cantidad vendida del inventario.

### Usuarios

Permite gestionar usuarios del sistema, incluyendo usuarios administradores y vendedores.

### Reportes

Permite exportar reportes de ventas en formato Excel.

## Requisitos previos

Antes de ejecutar el proyecto, se debe tener instalado:

- Python 3.x
- MySQL Server
- MySQL Workbench
- Git

## Instalación del proyecto

Clonar el repositorio:

    git clone https://github.com/contactodexstevqn-gif/ProyectoFinal.git

Entrar a la carpeta del proyecto:

    cd ProyectoFinal

Crear un entorno virtual:

    python -m venv venv

Activar el entorno virtual en Windows:

    venv\Scripts\activate

Instalar las dependencias del proyecto:

    pip install -r requirements.txt

## Configuración de la base de datos

El proyecto utiliza MySQL como sistema gestor de base de datos.

Crear una base de datos en MySQL:

    CREATE DATABASE prueba CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

Verificar en el archivo `backend/settings.py` que la configuración de la base de datos coincida con la configuración local:

    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': 'prueba',
            'USER': 'root',
            'PASSWORD': '',
            'HOST': 'localhost',
            'PORT': '3306',
        }
    }

Si el usuario de MySQL tiene contraseña, se debe colocar en el campo `PASSWORD`.

## Migraciones

Aplicar las migraciones para crear las tablas en la base de datos:

    python manage.py makemigrations
    python manage.py migrate

## Crear usuario administrador

Crear un superusuario para acceder al panel de administración de Django:

    python manage.py createsuperuser

Luego seguir las instrucciones de la terminal para ingresar usuario, correo y contraseña.

## Ejecutar el proyecto

Ejecutar el servidor de desarrollo:

    python manage.py runserver

Abrir el navegador en:

    http://127.0.0.1:8000/

Panel de administración de Django:

    http://127.0.0.1:8000/admin/

## Uso básico del sistema

1. Iniciar sesión con un usuario registrado.
2. Ingresar al módulo de productos para crear categorías y productos.
3. Revisar el inventario para consultar productos disponibles, productos con stock bajo y productos sin stock.
4. Usar la opción de ajustar stock para registrar entradas, salidas o correcciones.
5. Registrar ventas desde el módulo correspondiente.
6. Consultar reportes y exportaciones en Excel.

## Operaciones CRUD

El sistema permite realizar operaciones CRUD en diferentes módulos:

- Crear, listar, editar y eliminar productos.
- Crear y consultar categorías.
- Crear y gestionar usuarios.
- Registrar y consultar ventas.
- Registrar y consultar movimientos de inventario.

## Estructura general del proyecto

    ProyectoFinal/
    ├── backend/
    ├── productos/
    ├── usuarios/
    ├── ventas/
    ├── static/
    ├── templates/
    ├── manage.py
    ├── requirements.txt
    └── README.md

## Archivos importantes

### `manage.py`

Archivo principal para ejecutar comandos de Django como migraciones, servidor y creación de usuarios.

### `backend/settings.py`

Archivo de configuración principal del proyecto. Contiene la configuración de aplicaciones instaladas, base de datos, archivos estáticos y zona horaria.

### `templates/`

Carpeta donde se encuentran las plantillas HTML del sistema.

### `static/`

Carpeta donde se encuentran los archivos CSS, JavaScript e imágenes utilizadas en la interfaz.

### `productos/`

Aplicación encargada de gestionar productos, categorías, inventario y movimientos de stock.

### `ventas/`

Aplicación encargada de registrar ventas y consultar información relacionada.

### `usuarios/`

Aplicación encargada de la gestión de usuarios, login y permisos del sistema.

## Base de datos

El proyecto está conectado a una base de datos MySQL. Para la entrega final se recomienda incluir una exportación de la base de datos en formato `.sql`.

Nombre sugerido del archivo:

    tonjeo_boutique.sql

Ubicación recomendada:

    database/tonjeo_boutique.sql

Para restaurar la base de datos desde consola:

    mysql -u root -p prueba < database/tonjeo_boutique.sql

Si el usuario root no tiene contraseña:

    mysql -u root prueba < database/tonjeo_boutique.sql

## Dependencias

El archivo `requirements.txt` debe incluir las librerías necesarias para ejecutar el proyecto.

Ejemplo:

    Django==4.2.11
    mysqlclient==2.2.4
    pandas==2.2.2
    openpyxl==3.1.5
    Pillow==10.4.0
    reportlab==4.2.5

También se puede generar automáticamente con:

    pip freeze > requirements.txt

## Configuración adicional

Si se utiliza un archivo `.env`, se puede crear un archivo `.env.example` para documentar las variables necesarias:

    SECRET_KEY=django-insecure-cambia-esta-clave
    DEBUG=True
    DB_NAME=prueba
    DB_USER=root
    DB_PASSWORD=
    DB_HOST=localhost
    DB_PORT=3306

## Reportes

El sistema permite exportar reportes en formato Excel, utilizando las librerías Pandas y OpenPyXL.

## Estado del proyecto

Proyecto académico desarrollado para el curso Herramientas Computacionales.

## Integrantes

- Freddy Castro
- Stiven Mendoza
- Santiago Vasquez
- Keiner Perez

## Configuración del sistema

El sistema incluye una sección de **Configuración** disponible para administradores desde el menú lateral.

Desde allí se puede cambiar:

- Nombre de la tienda.
- Teléfono / WhatsApp de contacto.
- Dirección.
- Correo de contacto.
- Stock mínimo para alertas.
- Tema por defecto: oscuro o claro.
- Si el catálogo público muestra productos agotados.

