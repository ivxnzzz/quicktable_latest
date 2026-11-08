def classFactory(iface):
    from .quicktable.layer_filter import QuickFilter
    return QuickFilter(iface)
