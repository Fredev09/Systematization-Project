from django import forms

from .models import ConfiguracionTienda


class ConfiguracionTiendaForm(forms.ModelForm):
    class Meta:
        model = ConfiguracionTienda
        fields = [
            'nombre_tienda',
            'telefono',
            'direccion',
            'correo',
            'stock_minimo_alerta',
            'tema_defecto',
            'mostrar_agotados_catalogo',
        ]

        widgets = {
            'nombre_tienda': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ej: Mi Empresa'
            }),
            'telefono': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ej: 573001234567'
            }),
            'direccion': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ej: Carrera 10 # 20-30'
            }),
            'correo': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ej: tienda@correo.com'
            }),
            'stock_minimo_alerta': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'step': '1'
            }),
            'tema_defecto': forms.Select(attrs={
                'class': 'form-select'
            }),
            'mostrar_agotados_catalogo': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
        }

        labels = {
            'nombre_tienda': 'Nombre de la tienda',
            'telefono': 'Teléfono / WhatsApp',
            'direccion': 'Dirección',
            'correo': 'Correo de contacto',
            'stock_minimo_alerta': 'Stock mínimo para alerta',
            'tema_defecto': 'Tema por defecto',
            'mostrar_agotados_catalogo': 'Mostrar productos agotados en catálogo público',
        }

        help_texts = {
            'stock_minimo_alerta': 'Los productos con stock entre 1 y este número aparecerán como stock bajo.',
            'tema_defecto': 'Al guardar, también se aplicará en este navegador. Para otros usuarios funciona como tema inicial si no han elegido uno antes.',
        }

    def clean_stock_minimo_alerta(self):
        stock_minimo_alerta = self.cleaned_data['stock_minimo_alerta']

        if stock_minimo_alerta < 1:
            raise forms.ValidationError('El stock mínimo debe ser mayor o igual a 1.')

        return stock_minimo_alerta
