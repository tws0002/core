# Standard library
import os
import sys
import importlib
import contextlib

# Pyblish libraries
import pyblish.api

# Host libraries
import hou

# Local libraries
from . import lib
from ..lib import logger
from avalon import api, schema


self = sys.modules[__name__]
self._has_been_setup = False
self._parent = None
self._events = dict()


def install(config):
    """Setup integration
    Register plug-ins and integrate into the host

    """

    # _register_callbacks()

    if self._has_been_setup:
        teardown()

    pyblish.api.register_host("houdini")
    pyblish.api.register_host("hython")
    pyblish.api.register_host("hpython")

    self._has_been_setup = True

    config = find_host_config(config)
    if hasattr(config, "install"):
        config.install()


def uninstall():

    pyblish.api.deregister_host("hpython")
    pyblish.api.deregister_host("houdini")

    pass


def find_host_config(config):
    config_name = config.__name__
    try:
        config = importlib.import_module(config_name + ".houdini")
    except ImportError as exc:
        if str(exc) != "No module name {}".format(config_name + ".houdini"):
            raise
        config = None

    return config


def _discover_gui():
    """Return the most desirable of the currently registered GUIs"""

    # Prefer last registered
    guis = reversed(pyblish.api.registered_guis())

    for gui in guis:
        try:
            gui = __import__(gui).show
        except (ImportError, AttributeError):
            continue
        else:
            return gui


def teardown():
    """Remove integration"""
    if not self._has_been_setup:
        return

    self._has_been_setup = False
    print("pyblish: Integration torn down successfully")


@contextlib.contextmanager
def maintained_selection():
    """Maintain selection during context
    Example:
        >>> with maintained_selection():
        ...     # Modify selection
        ...     node.setSelected(on=False, clear_all_selected=True)
        >>> # Selection restored
    """

    previous_selection = hou.selectedNodes()
    try:
        yield
    finally:
        if previous_selection:
            for node in previous_selection:
                node.setSelected(on=True)
        else:
            for node in previous_selection:
                node.setSelected(on=False)


def containerise(name,
                 namespace,
                 nodes,
                 context,
                 loader=None,
                 suffix=""):
    """Bundle `nodes` into an assembly and imprint it with metadata

    Containerisation enables a tracking of version, author and origin
    for loaded assets.

    Arguments:
        name (str): Name of resulting assembly
        namespace (str): Namespace under which to host container
        nodes (list): Long names of nodes to containerise
        context (dict): Asset information
        loader (str, optional): Name of loader used to produce this container.
        suffix (str, optional): Suffix of container, defaults to `_CON`.

    Returns:
        container (str): Name of container assembly

    """

    # Get the node which is a direct child of the root, hou.node("/obj")
    container = next(n for n in nodes if n.parent() == hou.node("/obj"))
    data = {
        "schema": "avalon-core:container-2.0",
        "id": "pyblish.avalon.container",
        "name": name,
        "namespace": namespace,
        "loader": str(loader),
        "representation": str(context["representation"]["_id"]),
    }

    lib.imprint(container, data)

    return container


def parse_container(container, validate=True):
    """Return the container node's full container data.

    Args:
        container (str): A container node name.

    Returns:
        dict: The container schema data for this container node.

    """
    data = lib.read(container)

    # Backwards compatibility pre-schemas for containers
    data["schema"] = data.get("schema", "avalon-core:container-1.0")

    # Append transient data
    data["objectName"] = container.path()
    data["node"] = container

    if validate:
        schema.validate(data)

    return data


def ls():
    containers = []
    for identifier in ("pyblish.avalon.container",
                       "pyblish.mindbender.container"):
        containers += lib.lsattr("id", identifier)

    for container in sorted(containers):
        data = parse_container(container)
        yield data


class Creator(api.Creator):
    """Creator plugin to create instances in Houdini

    To support the wide range of node types for render output (Alembic, VDB,
    Mantra) the Creator needs a node type to create the correct instance

    By default, if none is given, is `geometry`. An example of accepted node
    types: geometry, alembic, ifd (mantra)

    Please check the Houdini documentation for more node types.

    Tip: to find the exact node type to create press the `i` left of the node
    when hovering over a node. The information is visible under the name of
    the node.

    """

    def __init__(self, *args, **kwargs):
        api.Creator.__init__(self, *args, **kwargs)
        self.nodes = list()

    def process(self):
        """This is the base functionality to create instances in Houdini

        The selected nodes are stored in self to be used in an override method.
        This is currently necessary in order to support the multiple output
        types in Houdini which can only be rendered through their own node.

        Default node type if none is given is `geometry`

        It also makes it easier to apply custom settings per instance type

        Example of override method for Alembic:

            def process(self):
                instance =  super(CreateEpicNode, self, process()
                # Set paramaters for Alembic node
                instance.setParms(
                    {"sop_path": "$HIP/%s.abc" % self.nodes[0]}
                )

        Returns:
            hou.Node

        """

        if (self.options or {}).get("useSelection"):
            self.nodes = hou.selectedNodes()

        # Get the node type and remove it from the data, not needed
        node_type = self.data.pop("node_type", None)
        if node_type is None:
            node_type = "geometry"

        # Get out node
        out = hou.node("out")
        instance = out.createNode(node_type, node_name=self.name)
        instance.moveToGoodPosition()

        lib.imprint(instance, self.data)

        return instance


def _on_scene_open(*args):
    api.emit("open", *[])


def _on_scene_new(*args):
    api.emit("new", *[])


def _on_scene_save(*args):
    api.emit("save", *[])


def on_houdini_initialize():

    main_window = hou.qt.mainWindow()
    self._parent = {main_window.objectName(): main_window}


def _register_callbacks():

    for handler, event in self._events.copy().items():
        if event is None:
            continue

        try:
            hou.hipFile.removeEventCallback(event)
        except RuntimeError as e:
            logger.info(e)

    self._events[_on_scene_save] = hou.hipFile.addEventCallback(_on_scene_save)

    self._events[_on_scene_new] = hou.hipFile.addEventCallback(_on_scene_new)

    self._events[_on_scene_open] = hou.hipFile.addEventCallback(_on_scene_open)
