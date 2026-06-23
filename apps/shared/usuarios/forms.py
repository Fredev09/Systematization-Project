from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password


class VendedorForm(forms.ModelForm):
    contra = forms.CharField(
        label='Contraseña',
        widget=forms.PasswordInput()
    )

    confirmarContra = forms.CharField(
        label='Confirmar contraseña',
        widget=forms.PasswordInput()
    )

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'username', 'email']

    def clean(self):
        cleaned_data = super().clean()

        contra = cleaned_data.get('contra')
        confirmarContra = cleaned_data.get('confirmarContra')

        if contra and confirmarContra and contra != confirmarContra:
            raise forms.ValidationError('Las contraseñas no coinciden.')

        return cleaned_data


class VendedorEditForm(forms.ModelForm):
    nueva_contrasena = forms.CharField(
        label='Nueva contraseña',
        required=False,
        widget=forms.PasswordInput(attrs={
            'placeholder': 'Dejar vacío para no cambiarla',
            'autocomplete': 'new-password'
        })
    )

    confirmar_contrasena = forms.CharField(
        label='Confirmar nueva contraseña',
        required=False,
        widget=forms.PasswordInput(attrs={
            'placeholder': 'Repite la nueva contraseña',
            'autocomplete': 'new-password'
        })
    )

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'username', 'email']

        widgets = {
            'first_name': forms.TextInput(attrs={
                'placeholder': 'Nombre del vendedor'
            }),
            'last_name': forms.TextInput(attrs={
                'placeholder': 'Apellido del vendedor'
            }),
            'username': forms.TextInput(attrs={
                'placeholder': 'Usuario de acceso'
            }),
            'email': forms.EmailInput(attrs={
                'placeholder': 'Correo electrónico'
            }),
        }

        labels = {
            'first_name': 'Nombre',
            'last_name': 'Apellido',
            'username': 'Vendedor',
            'email': 'Correo'
        }

    def clean(self):
        cleaned_data = super().clean()
        nueva_contrasena = cleaned_data.get('nueva_contrasena')
        confirmar_contrasena = cleaned_data.get('confirmar_contrasena')

        if nueva_contrasena or confirmar_contrasena:
            if not nueva_contrasena:
                self.add_error('nueva_contrasena', 'Ingresa la nueva contraseña.')
            if not confirmar_contrasena:
                self.add_error('confirmar_contrasena', 'Confirma la nueva contraseña.')
            if nueva_contrasena and confirmar_contrasena and nueva_contrasena != confirmar_contrasena:
                self.add_error('confirmar_contrasena', 'Las contraseñas no coinciden.')
            if nueva_contrasena:
                validate_password(nueva_contrasena, self.instance)

        return cleaned_data

    def save(self, commit=True):
        usuario = super().save(commit=False)
        nueva_contrasena = self.cleaned_data.get('nueva_contrasena')

        if nueva_contrasena:
            usuario.set_password(nueva_contrasena)

        if commit:
            usuario.save()

        return usuario
