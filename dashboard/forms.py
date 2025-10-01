from django import forms

from accounts.models import CoreSettings


class CoreSettingsForm(forms.ModelForm):
    class Meta:
        model = CoreSettings
        fields = ['default_vat_rate', 'default_stock_level']
        widgets = {
            'default_vat_rate': forms.Select(attrs={'class': 'select select-bordered w-full'}),
            'default_stock_level': forms.NumberInput(attrs={'class': 'input input-bordered w-full', 'min': 0}),
        }
        labels = {
            'default_vat_rate': 'Domyślna stawka VAT',
            'default_stock_level': 'Domyślny stan magazynowy',
        }
        help_texts = {
            'default_vat_rate': 'Stawka zostanie zasugerowana przy tworzeniu nowych produktów.',
            'default_stock_level': 'Wartość zostanie proponowana dla pola stock.stock (liczba sztuk).',
        }

    def clean_default_stock_level(self):
        value = self.cleaned_data['default_stock_level']
        if value is None:
            return 0
        if value < 0:
            raise forms.ValidationError('Stan magazynowy nie może być ujemny.')
        return value
