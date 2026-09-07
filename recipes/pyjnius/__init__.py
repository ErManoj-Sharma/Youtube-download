from os.path import join
from pythonforandroid.recipes.pyjnius import PyjniusRecipe as _BasePyjniusRecipe
from pythonforandroid.util import current_directory
from pythonforandroid.logger import shprint, info
import sh
import glob


class PyjniusRecipe(_BasePyjniusRecipe):
    extra_build_args = ["--no-isolation"]

    def build_arch(self, arch):
        env = self.get_recipe_env(arch, with_flags_in_cc=True)

        # Install Cython + wheel into hostpython3 site-packages
        # so --no-isolation build can resolve them
        self.install_hostpython_prerequisites(
            packages=["Cython==3.0.0", "wheel"]
        )

        # Also install into the target python's site-packages
        # because `python -m build --no-isolation` checks the target binary
        target_site = join(
            self.ctx.python_recipe.get_build_dir(arch),
            "android-build", "Lib", "site-packages"
        )
        from pythonforandroid.util import ensure_dir
        ensure_dir(target_site)
        shprint(
            sh.pip, "install", "Cython==3.0.0", "wheel",
            "--target", target_site,
            "--only-binary=:all:",
            _env=env,
        )

        # Now call parent build_arch (which runs python -m build --no-isolation)
        _BasePyjniusRecipe.build_arch(self, arch)


recipe = PyjniusRecipe()
