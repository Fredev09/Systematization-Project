from django import forms

from .models import Campo, Formulario


class FormularioForm(forms.ModelForm):
    generar_identificador = forms.TypedChoiceField(
        coerce=lambda x: x == 'True',
        choices=[(True, 'Crear automáticamente un identificador principal'),
                 (False, 'Yo crearé mi propio identificador principal manualmente')],
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
        initial=True,
        required=True,
        label='Identificación del formulario',
    )
    nombre_identificador = forms.CharField(
        max_length=100,
        required=False,
        initial='Código',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ej: Código, ID, Referencia'
        }),
        label='Nombre del campo identificador',
    )
    mostrar_en_tablas = forms.TypedChoiceField(
        coerce=lambda x: x == 'True',
        choices=[(True, 'Sí'), (False, 'No')],
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
        initial=True,
        required=False,
        label='Mostrar en tablas',
    )

    class Meta:
        model = Formulario
        fields = ['nombre', 'descripcion', 'activo']
        widgets = {
            'nombre': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ej: Inventario Junio, Control de Vehículos'
            }),
            'descripcion': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Descripción opcional del formulario'
            }),
            'activo': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
        }
        labels = {
            'nombre': 'Nombre del formulario',
            'descripcion': 'Descripción',
            'activo': 'Formulario activo',
        }


class CampoForm(forms.ModelForm):
    class Meta:
        model = Campo
        fields = ['nombre', 'tipo', 'obligatorio', 'unico', 'visible', 'descripcion', 'orden', 'opciones']
        widgets = {
            'nombre': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ej: Nombre del producto'
            }),
            'tipo': forms.Select(attrs={
                'class': 'form-select'
            }),
            'obligatorio': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'unico': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'visible': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'descripcion': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Descripción opcional del campo'
            }),
            'orden': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0'
            }),
            'opciones': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Para listas desplegables, escribe cada opción separada por coma. Ej: Rojo, Verde, Azul'
            }),
        }
        labels = {
            'nombre': 'Nombre del campo',
            'tipo': 'Tipo de dato',
            'obligatorio': 'Campo obligatorio',
            'unico': 'Valor único',
            'visible': 'Campo visible',
            'descripcion': 'Descripción',
            'orden': 'Orden',
            'opciones': 'Opciones (para listas desplegables)',
        }


