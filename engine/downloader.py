import pkgutil
import importlib
import re
import engine
from engine.plugins import general


class Extractor(object):
    def __init__(self):
        self.plugins = []
        self.load_plugins(engine.plugins.__path__[0])

    def load_plugins(self, path):
        """Attempt to load plugins from the path specified.

        :param path: full path to a directory where to look for plugins

        """
        for loader, name, ispkg in pkgutil.iter_modules([path]):
            # set the full plugin module name
            module_name = "engine.plugins.{0}".format(name)
            # print(module_name)
            self.load_plugin(module_name)
        # print(self.plugins)

    def load_plugin(self, name):
        # Set the global http session for this plugin
        module = importlib.import_module(name)

        if hasattr(module, "VALID_URL_BASE"):
            # module_name = getattr(module, "__name__")
            # plugin_name = module_name.split(".")[-1]  # get the plugin part of the module name

            if module in self.plugins:
                print('存在')
                return

            self.plugins.append(module)

    @staticmethod
    def suit_url(pattern, urls):
        sorted_url = []
        for i in range(len(urls) - 1, -1, -1):
            if re.match(pattern, urls[i]):
                sorted_url.append(urls[i])
                urls.remove(urls[i])
        return sorted_url

    def sorted_checker(self, urls, signature='API_ROOMS'):
        curls = urls.copy()
        batches = []
        onebyone = []
        for plugin in self.plugins:
            plugin.__plugin__.url_list = self.suit_url(plugin.VALID_URL_BASE, curls)
            if hasattr(plugin, signature):
                batches.append(plugin.BatchCheck(plugin.__plugin__.url_list))
            else:
                onebyone.append(plugin.__plugin__)
        general.__plugin__.url_list = curls
        onebyone.append(general.__plugin__)
        # onebyone.append(__import__('engine.plugins.general', fromlist=['general',]))
        return batches, onebyone


def download(fname, url):
    extractor = Extractor()
    plugins = extractor.plugins
    for plugin in plugins:
        if hasattr(plugin, "VALID_URL_BASE"):
            if re.match(plugin.VALID_URL_BASE, url):
                plugin.__plugin__(fname, url).run()
                return
    general.__plugin__(fname, url).run()
