def classFactory(iface):
    # Ensure latest code is loaded when the plugin is (re)enabled in QGIS.
    import importlib

    from . import arch_distribution_dialog
    from . import arch_distribution

    importlib.reload(arch_distribution_dialog)
    importlib.reload(arch_distribution)

    return arch_distribution.ArchDistribution(iface)
