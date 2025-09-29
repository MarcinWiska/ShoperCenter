from django import forms
from .models import Shop


class ShopForm(forms.ModelForm):
    class Meta:
        model = Shop
        fields = ["name", "base_url", "bearer_token"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "input input-bordered w-full"}),
            "base_url": forms.URLInput(attrs={"class": "input input-bordered w-full"}),
            "bearer_token": forms.TextInput(attrs={"class": "input input-bordered w-full"}),
        }

    def clean_base_url(self):
        url = self.cleaned_data.get("base_url", "").rstrip('/')
        # Jeżeli użytkownik nie podał '/webapi' ani '/rest', spróbuj zasugerować '/webapi'
        if not url.endswith('/webapi') and not url.endswith('/webapi/rest') and not url.endswith('/rest'):
            url = url + '/webapi'
        return url
