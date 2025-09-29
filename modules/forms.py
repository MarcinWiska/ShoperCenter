from django import forms
from .models import Module


class ModuleCreateForm(forms.ModelForm):
    class Meta:
        model = Module
        fields = ["shop", "name", "resource", "api_path_override"]
        widgets = {
            "shop": forms.Select(attrs={"class": "select select-bordered w-full"}),
            "name": forms.TextInput(attrs={"class": "input input-bordered w-full"}),
            "resource": forms.Select(attrs={"class": "select select-bordered w-full"}),
            "api_path_override": forms.TextInput(attrs={"class": "input input-bordered w-full", "placeholder": "np. products"}),
        }

