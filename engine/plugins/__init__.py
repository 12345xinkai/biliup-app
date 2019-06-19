import os
import re
import subprocess
import sys
import time
from threading import Thread, Event
import psutil
import streamlink
import youtube_dl
from common import logger
from common.timer import Timer
from engine.db import DBSession
from engine.db.LinksId import Pricipal


class DownloadBase:
    url_list = None

    def __init__(self, fname, url, suffix=None):
        self.fname = fname
        self.url = url
        self.suffix = suffix
        self.flag = None
        self.ydl_opts = {}

    def check_stream(self):
        logger.debug(self.fname)

    def dl(self, file_name):
        pid = os.getpid()
        monitor = Monitoring(pid, file_name)
        monitor.url = self.url
        self.flag = monitor.flag
        t = Thread(target=monitor.start)
        t.start()
        retval = self.download()
        monitor.stop()
        if not self.flag.is_set():
            return 0
        return retval

    def download(self):
        pass

    def run(self):
        file_name = self.file_name
        self.ydl_opts = {'outtmpl': file_name}
        if self.check_stream():
            try:
                logger.info('开始下载%s：%s' % (self.__class__.__name__, self.fname))
                retval = self.dl(file_name)
                self.rename(file_name)

                if retval != 0:
                    logger.info('准备递归下载')
                    self.run()
                else:
                    logger.info('下载完成' + self.fname)

            finally:
                logger.info('退出下载')

    @staticmethod
    def rename(file_name):
        try:
            os.rename(file_name + '.part', file_name)
            logger.info('更名{0}为{1}'.format(file_name + '.part', file_name))
        except FileNotFoundError:
            logger.info('FileNotFoundError:' + file_name)
        except FileExistsError:
            os.rename(file_name + '.part', file_name)
            logger.info('FileExistsError:更名{0}为{1}'.format(file_name + '.part', file_name))

    @property
    def file_name(self):
        file_name = '%s%s.%s' % (self.fname, str(time.time())[:10], self.suffix)
        return file_name


class YDownload(DownloadBase):
    # url_list = None

    def __init__(self, fname, url, suffix='flv'):
        super().__init__(fname, url, suffix)

    def check_stream(self):
        try:
            self.get_sinfo()
            return True
        except youtube_dl.utils.DownloadError:
            logger.debug('%s未开播或读取下载信息失败' % self.fname)
            return False

    def get_sinfo(self):
        info_list = []
        with youtube_dl.YoutubeDL() as ydl:
            # cu = self.url.get(self.__class__.__name__)
            if self.url:
                info = ydl.extract_info(self.url, download=False)
            else:
                logger.debug('%s不存在' % self.__class__.__name__)
                return
            for i in info['formats']:
                info_list.append(i['format_id'])
            logger.debug(info_list)
        return info_list

    def download(self):
        try:
            with youtube_dl.YoutubeDL(self.ydl_opts) as ydl:
                # ydl.download([self.url[self.__class__.__name__]])
                ydl.download([self.url])
        except youtube_dl.utils.DownloadError:
            return 1
        return 0


class SDownload(DownloadBase):
    def __init__(self, fname, url, suffix='mp4'):
        super().__init__(fname, url, suffix)
        self.stream = None

    def check_stream(self):
        logger.debug(self.fname)
        streams = streamlink.streams(self.url)
        try:
            if streams:
                self.stream = streams["best"]
                fd = self.stream.open()
                fd.close()
                return True
        except streamlink.StreamlinkError:
            return

    def download(self):
        try:
            with self.stream.open() as fd:
                with open(self.ydl_opts['outtmpl'] + '.part', 'wb') as file:
                    for f in fd:
                        file.write(f)
                        if self.flag.is_set():
                            # self.flag.clear()
                            return 1
                    return 0
        except OSError:
            self.rename(self.ydl_opts['outtmpl'])
            raise


class FFmpegdl(DownloadBase):
    def download(self):
        args = ['ffmpeg', '-y', '-i', self.ydl_opts['absurl'], '-c', 'copy', '-f', 'flv',
                self.ydl_opts['outtmpl'] + '.part']
        proc = subprocess.Popen(args, stdin=subprocess.PIPE)
        try:
            retval = proc.wait()
        except KeyboardInterrupt:
            if sys.platform != 'win32':
                proc.communicate(b'q')
            raise
        return retval


class BatchCheckBase:
    def __init__(self, pattern_id, urls):
        self.usr_dict = {}
        self.usr_list = []
        self.pattern_id = pattern_id
        for url in urls:
            self.get_id(url)

    def get_id(self, url):
        m = re.match(self.pattern_id, url)
        if m:
            usr_id = m.group('id')
            self.usr_dict[usr_id.lower()] = url
            self.usr_list.append(usr_id)

    def check(self):
        pass


class Monitoring(Timer):
    def __init__(self, parent_pid, file_name):
        super().__init__(func=self.kill_child_processes, interval=3)
        self.parent = self.children = self.numc = None
        self.parent_pid = parent_pid
        self.file_name = file_name + '.part'
        self.last_file_size = 0.0
        self.flag = Event()
        self.frozen_time = time.time()
        self.ago = self.frozen_time
        self.url = None

    def terminate(self):
        if self.numc == 0:
            logger.error("ChildrenProcess doesn't exist")
        else:
            for process in self.children:
                process.terminate()
            # logger.info('下载卡死' + self.file_name)

    def get_process(self, parent_pid):
        try:
            parent = psutil.Process(parent_pid)
        except psutil.NoSuchProcess:
            self.stop()
            logger.error("Process doesn't exist")
            return
        children = parent.children(recursive=True)
        numc = len(children)
        return parent, children, numc

    def kill_child_processes(self):
        pricipal = DBSession().query(Pricipal).filter(Pricipal.room_url == self.url).one()
        DBSession.remove()

        file_size = os.path.getsize(self.file_name)
        now = time.time()

        if now-self.ago > 15:
            if file_size <= self.last_file_size:
                logger.error('下载卡死' + self.file_name)
                if self.numc == 0:
                    self.parent.terminate()
                else:
                    self.terminate()
                time.sleep(1)
                if os.path.isfile(self.file_name):
                    logger.info('卡死下载进程可能未成功退出')
                    return
                else:
                    self.stop()
                    logger.info('卡死下载进程成功退出')
                    return
            self.last_file_size = file_size
            self.ago = now
        if pricipal.remaining_time-(now-self.frozen_time) <= 0:
            if self.numc == 0:
                db_session = DBSession()
                pricipal = db_session.query(Pricipal).filter(Pricipal.room_url == self.url).one()
                pricipal.remaining_time = pricipal.remaining_time - (time.time() - self.frozen_time)
                db_session.commit()
                DBSession.remove()
                self.parent.terminate()
            else:
                self.terminate()
            logger.info('%s余额不足' % self.url)

        if file_size >= 2.5 * 1024 ** 3:
            self.flag.set()
            self.terminate()
            logger.info('分段下载' + self.file_name)

    def __timer(self):
        logger.info('获取到{0}，{1}'.format(self.parent_pid, self.file_name))
        retry = 0

        while not self._flag.wait(self.interval):
            self.parent, self.children, self.numc = self.get_process(self.parent_pid)
            if os.path.isfile(self.file_name):
                self._func(*self._args, **self._kwargs)
            else:
                logger.info('%s不存在' % self.file_name)
                if retry >= 2:
                    self.terminate()
                    logger.info('结束进程，找不到%s' % self.file_name)
                    return
                retry += 1
                # logger.info('监控<%s>线程退出' % self.file_name)

    def start(self):
        try:
            self.__timer()
        finally:
            logger.info('退出监控<%s>线程' % self.file_name)

    def stop(self):
        db_session = DBSession()
        pricipal = db_session.query(Pricipal).filter(Pricipal.room_url == self.url).one()
        pricipal.remaining_time = pricipal.remaining_time-(time.time()-self.frozen_time)
        db_session.commit()
        DBSession.remove()
        self._flag.set()


def match1(text, *patterns):
    if len(patterns) == 1:
        pattern = patterns[0]
        match = re.search(pattern, text)
        if match:
            return match.group(1)
        else:
            return None
    else:
        ret = []
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                ret.append(match.group(1))
        return ret
