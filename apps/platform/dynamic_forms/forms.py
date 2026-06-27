from django import forms

from .models import Campo, Formulario


class FormularioForm(forms.ModelForm):
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
        fields = ['nombre', 'tipo', 'obligatorio', 'orden', 'opciones']
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
            'orden': 'Orden',
            'opciones': 'Opciones (para listas desplegables)',
        }


