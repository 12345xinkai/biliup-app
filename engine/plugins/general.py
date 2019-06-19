from common import logger
from engine.plugins import FFmpegdl
from ykdl.common import url_to_module


class Generic(FFmpegdl):
    def __init__(self, fname, url, suffix='flv'):
        super().__init__(fname, url, suffix)

    def check_stream(self):
        logger.debug(self.fname)
        site, url = url_to_module(self.url)
        try:
            info = site.parser(url)
        except AssertionError:
            return
        stream_id = info.stream_types[0]
        urls = info.streams[stream_id]['src']
        self.ydl_opts['absurl'] = urls[0]
        # print(info.title)
        return True


__plugin__ = Generic
