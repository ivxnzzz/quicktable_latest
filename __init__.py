def classFactory(iface):
    from .layer_filter import QuickFilter
    return QuickFilter(iface)
