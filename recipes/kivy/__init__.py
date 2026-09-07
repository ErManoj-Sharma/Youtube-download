from os.path import join
from pythonforandroid.recipes.kivy import KivyRecipe as _BaseKivyRecipe
from pythonforandroid.util import ensure_dir
from pythonforandroid.logger import shprint
import sh


class KivyRecipe(_BaseKivyRecipe):
    extra_build_args = ["--no-isolation"]

    def build_arch(self, arch):
        # Kivy's pyproject.toml build-requirements under --no-isolation
        # must already be present in both hostpython3 and the target
        # python's site-packages.
        reqs = [
            "Cython>=0.29.1,<=3.0.11",
            "setuptools==69.2.0",
            "wheel~=0.44.0",
            "packaging~=24.0",
        ]
        self.install_hostpython_prerequisites(packages=reqs)

        target_site = join(
            self.ctx.python_recipe.get_build_dir(arch),
            "android-build", "Lib", "site-packages",
        )
        ensure_dir(target_site)
        env = self.get_recipe_env(arch, with_flags_in_cc=True)
        shprint(
            sh.pip, "install", *reqs,
            "--target", target_site,
            "--only-binary=:all:",
            _env=env,
        )

        _BaseKivyRecipe.build_arch(self, arch)


recipe = KivyRecipe()