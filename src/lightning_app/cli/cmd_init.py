import logging
import os
import re
import shutil

logger = logging.getLogger(__name__)


def app(app_name):

    if app_name is None:
        app_name = _capture_valid_app_component_name(resource_type="app")

    # generate resource template
    new_resource_name, name_for_files = _make_resource(resource_dir="app-template", resource_name=app_name)

    m = f"""
    ⚡ Lightning app template created! ⚡
    {new_resource_name}

    run your app with:
        lightning run app {app_name}/{name_for_files}/app.py

    run it on the cloud to share with your collaborators:
        lightning run app {app_name}/{name_for_files}/app.py --cloud
    """
    logger.info(m)


def _make_resource(resource_dir, resource_name):
    path = os.path.dirname(os.path.abspath(__file__))
    template_dir = os.path.join(path, resource_dir)
    name_for_files = re.sub("-", "_", resource_name)

    new_resource_name = os.path.join(os.getcwd(), resource_name)

    # lay out scaffolding
    logger.info(f"laying out component template at {new_resource_name}")
    shutil.copytree(template_dir, new_resource_name)

    # rename main folder
    os.rename(os.path.join(new_resource_name, "placeholdername"), os.path.join(new_resource_name, name_for_files))

    # for each file, rename the word
    trouble_names = {".DS_Store"}
    files = _ls_recursively(new_resource_name)
    for bad_file in files:
        if bad_file.split("/")[-1] in trouble_names:
            continue
        # find the words and replace
        content = open(bad_file).read().replace("placeholdername", name_for_files)
        with open(bad_file, "w") as file:
            file.write(content)

    # rename files
    for file in files:
        new_file = re.sub("placeholdername", name_for_files, file)
        os.rename(file, new_file)

    return new_resource_name, name_for_files


def _ls_recursively(dir_name):
    fname = []
    for root, d_names, f_names in os.walk(dir_name):
        for f in f_names:
            if "__pycache__" not in root:
                fname.append(os.path.join(root, f))

    return fname


def _capture_valid_app_component_name(value=None, resource_type="app"):
    prompt = f"""
    ⚡ Creating Lightning {resource_type} ⚡
    """
    logger.info(prompt)

    try:
        if value is None:
            value = input(f"\nName your Lightning {resource_type} (example: the-{resource_type}-name) >  ")
        value = value.strip().lower()
        unsafe_chars = set(re.findall(r"[^a-z0-9\-]", value))
        if len(unsafe_chars) > 0:
            m = f"""
            Error: your Lightning {resource_type} name:
            {value}

            contains the following unsupported characters:
            {unsafe_chars}

            A Lightning {resource_type} name can only contain letters (a-z) numbers (0-9) and the '-' character

            valid example:
            lightning-{resource_type}
            """
            raise SystemExit(m)

    except KeyboardInterrupt:
        m = f"""
        ⚡ {resource_type} init aborted! ⚡
        """
        raise SystemExit(m)

    return value


def component(component_name):
    if component_name is None:
        component_name = _capture_valid_app_component_name(resource_type="component")

    # generate resource template
    new_resource_name, name_for_files = _make_resource(resource_dir="component-template", resource_name=component_name)

    m = f"""
    ⚡ Lightning component template created! ⚡
    {new_resource_name}

    ⚡ To use your component, first pip install it (with these 3 commands): ⚡
    cd {component_name}
    pip install -r requirements.txt
    pip install -e .

    ⚡ Use the component inside an app: ⚡

    from {name_for_files} import TemplateComponent
    import lightning_app as la

    class LitApp(la.LightningFlow):
        def __init__(self) -> None:
            super().__init__()
            self.{name_for_files} = TemplateComponent()

        def run(self):
            print('this is a simple Lightning app to verify your component is working as expected')
            self.{name_for_files}.run()

    app = la.LightningApp(LitApp())

    ⚡ Checkout the demo app with your {component_name} component: ⚡
    lightning run {component_name}/app.py

    ⚡ Tip: Publish your component to the Lightning Gallery to enable users to install it like so:
    lightning install component YourLightningUserName/{component_name}

    so the Lightning community can use it like:
    from {name_for_files} import TemplateComponent

    """
    logger.info(m)
