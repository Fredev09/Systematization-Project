from django import forms

from .models import Producto


OPCIONES_TALLAS = [
    ('', 'Selecciona una talla'),
    ('XS', 'XS'),
    ('S', 'S'),
    ('M', 'M'),
    ('L', 'L'),
    ('XL', 'XL'),
    ('XXL', 'XXL'),
    ('Única', 'Única'),
    ('Ajustable', 'Ajustable'),
    ('6', '6'),
    ('8', '8'),
    ('10', '10'),
    ('12', '12'),
    ('14', '14'),
    ('16', '16'),
    ('28', '28'),
    ('30', '30'),
    ('32', '32'),
    ('34', '34'),
    ('36', '36'),
    ('38', '38'),
    ('40', '40'),
]


class ProductoForm(forms.ModelForm):
    talla = forms.ChoiceField(
        choices=OPCIONES_TALLAS,
        widget=forms.Select(attrs={
            'class': 'form-select'
        }),
        label='Talla'
    )

    class Meta:
        model = Producto
        fields = [
            'nombre',
            'categoria',
            'talla',
            'color',
            'precio',
            'stock',
            'imagen',
            'imagen_url'
        ]

        widgets = {
            'nombre': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nombre del producto'
            }),
            'categoria': forms.Select(attrs={
                'class': 'form-select'
            }),
            'color': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ej: Negro, Rosado, Blanco'
            }),
            'precio': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1000',
                'step': '1000',
                'placeholder': 'Ej: 50000'
            }),
            'stock': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0',
                'step': '1',
                'placeholder': 'Cantidad disponible'
            }),
            'imagen': forms.ClearableFileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            }),
            'imagen_url': forms.URLInput(attrs={
                'class': 'form-control',
                'placeholder': 'https://ejemplo.com/imagen.jpg'
            }),
        }

        labels = {
            'nombre': 'Nombre',
            'categoria': 'Categoria',
            'talla': 'Talla',
            'color': 'Color',
            'precio': 'Precio',
            'stock': 'Stock',
            'imagen': 'Imagen del producto',
            'imagen_url': 'URL de imagen'
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        talla_actual = self.initial.get('talla')

        if not talla_actual and self.instance and self.instance.pk:
            talla_actual = self.instance.talla

        valores = [valor for valor, texto in OPCIONES_TALLAS]

        if talla_actual and talla_actual not in valores:
            self.fields['talla'].choices = OPCIONES_TALLAS + [(talla_actual, f'{talla_actual} registrada')]


class ProductoEditForm(ProductoForm):
    class Meta(ProductoForm.Meta):
        fields = [
            'nombre',
            'categoria',
            'talla',
            'color',
            'precio',
            'imagen',
            'imagen_url'
        ]
