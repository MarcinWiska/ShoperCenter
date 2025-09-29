from django import forms
from .models import RedirectRule
from .shoper_redirects import _norm_path


class RedirectRuleForm(forms.ModelForm):
    class Meta:
        model = RedirectRule
        fields = [
            'shop', 'rule_type', 'source_url', 'product_id', 'category_id',
            'target_url', 'status_code'
        ]
        widgets = {
            'shop': forms.Select(attrs={'class': 'select select-bordered w-full'}),
            'rule_type': forms.Select(attrs={'class': 'select select-bordered w-full'}),
            'source_url': forms.TextInput(attrs={'class': 'input input-bordered w-full', 'placeholder': '/stara-strona'}),
            'product_id': forms.NumberInput(attrs={'class': 'input input-bordered w-full', 'placeholder': 'np. 123'}),
            'category_id': forms.NumberInput(attrs={'class': 'input input-bordered w-full', 'placeholder': 'np. 55'}),
            'target_url': forms.TextInput(attrs={'class': 'input input-bordered w-full', 'placeholder': '/nowa-strona'}),
            'status_code': forms.Select(attrs={'class': 'select select-bordered w-full'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields['shop'].queryset = self.fields['shop'].queryset.filter(owner=user)
        self.fields['target_url'].required = False

    def clean(self):
        cleaned = super().clean()
        t = cleaned.get('rule_type')
        source_url = cleaned.get('source_url') or ''
        product_id = cleaned.get('product_id')
        category_id = cleaned.get('category_id')
        target_url = cleaned.get('target_url')

        if t == RedirectRule.RuleType.URL_TO_URL:
            if not source_url:
                raise forms.ValidationError('Dla reguły URL→URL podaj źródłowy URL')
            if not target_url:
                raise forms.ValidationError('Dla reguły URL→URL podaj docelowy URL')
        elif t == RedirectRule.RuleType.PRODUCT_TO_URL:
            if not product_id:
                raise forms.ValidationError('Dla reguły Product→URL podaj ID produktu')
            if not target_url and product_id is not None:
                cleaned['target_url'] = _norm_path(f'/product/{product_id}')
                target_url = cleaned['target_url']
        elif t == RedirectRule.RuleType.CATEGORY_TO_URL:
            if not category_id:
                raise forms.ValidationError('Dla reguły Category→URL podaj ID kategorii')
            if not target_url and category_id is not None:
                cleaned['target_url'] = _norm_path(f'/category/{category_id}')
                target_url = cleaned['target_url']

        # Normalize URLs if provided so we store consistent paths
        if source_url:
            cleaned['source_url'] = _norm_path(source_url)
        if target_url:
            cleaned['target_url'] = _norm_path(target_url)
        return cleaned
