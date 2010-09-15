#!/usr/bin/env python
'''
ftpush.py - Copyright 2010, Ton van den Heuvel, Ecomation
'''

import ftplib, getpass, optparse, os, re, threading
import pyinotify

class Monitor(pyinotify.ProcessEvent):
    def __init__(self, url, username, path, ignore):
        self.path = os.path.abspath(path)
        self.url = url
        self.url += '/' if self.url[-1] != '/' else ''
        self.username = username
        self.ignore = [] if ignore == '' else ignore.split(',')

        wm = pyinotify.WatchManager()
        self.notifier = pyinotify.Notifier(wm, self)
        wm.add_watch(path, pyinotify.IN_CREATE | pyinotify.IN_CLOSE_WRITE | pyinotify.IN_DELETE |
                           pyinotify.IN_MOVED_FROM | pyinotify.IN_MOVED_TO, rec = True, auto_add = True)

        # Extract username, login, and remote path information from the FTP.
        matches = re.search('(?:ftp://)?(?:([^:]*):([^@]*)@|([^@]*)@)?([^/]*)(?:/(.*))?', self.url)
        if not self.username:
            self.username = matches.group(1) if matches.group(1) else matches.group(3)
        self.password = matches.group(2)
        self.server = matches.group(4)
        self.remote_path = matches.group(5)

        if self.username and not self.password:
            self.password = getpass.getpass('> Password: ')

        self.connect()
        self.keep_alive()

    def event_handler(f):
        def decorated(self, event):
            for regex in self.ignore:
                if re.match(regex, event.pathname):
                    return

            try:
                f(self, event)
            except ftplib.error_perm as error:
                print '! Error: %s' % error

        return decorated

    def connect(self):
        self.ftp = ftplib.FTP(self.server, self.username, self.password)

        if self.username:
            print "> Connected to '%s' with username '%s'..." % (self.server, self.username)
        else:
            print "> Connected to '%s'" % server

        self.ftp.cwd(self.remote_path)

        print "> Changed remote directory to '%s'" % self.remote_path

    def stop_keep_alive_timer(self):
        self.timer.cancel()

    def keep_alive(self):
        print "> Ping..."
        self.ftp.nlst()

        self.timer = threading.Timer(500, self.keep_alive)
        self.timer.start()

    def remove(self, pathname, is_dir):
        relative_path = os.path.relpath(pathname)

        if is_dir:
            # TODO: remove in case pyinotify issue #8 has been resolved, see
            # http://trac.dbzteam.org/pyinotify/ticket/8 for more information
            for pathname in self.ftp.nlst(relative_path):
                filename = pathname.split('/')[-1]
                if filename != '..' and filename != '.':
                    try:
                        self.remove(pathname, False)
                    except:
                        self.remove(pathname, True)

            self.ftp.rmd(relative_path)
            print "> Deleted directory '%s'..." % relative_path
        else:
            self.ftp.delete(relative_path)
            print "> Deleted '%s'..." % relative_path

    def upload(self, pathname):
        pathname = os.path.relpath(pathname)
        if os.path.isdir(pathname):
            self.ftp.mkd(pathname)
            print "> Created directory '%s'..." % pathname

            # TODO: remove in case pyinotify issue #8 has been resolved, see
            # http://trac.dbzteam.org/pyinotify/ticket/8 for more information
            for filename in os.listdir(pathname):
                self.upload(pathname + '/' + filename)
        else:
            filename = os.path.relpath(pathname)
            filesize = os.path.getsize(pathname)

            fp = open(pathname, 'r')
            self.ftp.storbinary('STOR ' + filename, fp)
            fp.close()

            print "> Uploaded '%s' (%d bytes)..." % (filename, filesize)

    @event_handler
    def process_IN_DELETE(self, event):
        '''Handle deleting files and directories.'''
        self.remove(event.pathname, event.dir)

    @event_handler
    def process_IN_CLOSE_WRITE(self, event):
        '''Handle writing of files.'''
        if event.dir:
            return

        self.upload(event.pathname)

    @event_handler
    def process_IN_CREATE(self, event):
        '''Handle creation of directories.'''
        if not event.dir:
            return

        self.upload(event.pathname)

    @event_handler
    def process_IN_MOVED_FROM(self, event):
        '''Handle moving files and directories out of the monitored directory.'''
        self.remove(event.pathname, event.dir)

    @event_handler
    def process_IN_MOVED_TO(self, event):
        '''Handle moving files and directories into the monitored directory.'''
        self.upload(event.pathname)

    def start(self):
        try:
            print "> Start monitoring '%s'..." % self.path
            self.notifier.loop()
        except (KeyboardInterrupt, SystemExit):
            pass

        # Stop keep alive thread.
        self.stop_keep_alive_timer()

        # TODO: raises an exception, maybe this is due to pyinotify 0.8.6,
        # check with updated 0.8.9 whether this still happens
        try:
            self.notifier.stop()
        except:
            pass

if __name__ == '__main__':
    parser = optparse.OptionParser(description = 'Monitor a local directory for file changes and automatically upload a modified file '
                                                 'to a remote FTP.',
                                   version = "0.0.1",
                                   usage = 'usage: %prog -u,--url=<url> -p,--path=<local path> [ -i,--ignore=<ignore files> ]',
                                   epilog = 'Copyright 2010, Ton van den Heuvel, Ecomation, see LICENSE for more details.')
    parser.add_option('-f', '--ftp',
                      dest = 'url',
                      help = 'remote FTP path to synchronise with, may include username and password information')
    parser.add_option('-u', '--user',
                      dest = 'username',
                      help = 'username to login with')
    parser.add_option('-p', '--path',
                      dest = 'path',
                      default = '.',
                      help = 'local directory to synchronise')
    parser.add_option('-i', '--ignore',
                      dest = 'ignore',
                      default = '',
                      help = 'comma separated list of regular expressions matching files to ignore')
    (options, args) = parser.parse_args()
    if not options.url or not options.path:
        parser.print_usage()
    else:
        monitor = Monitor(options.url, options.username, options.path, options.ignore)
        try:
            monitor.start()
        except Exception as e:
            monitor.stop_keep_alive_timer()
            print "\n> Fatal error monitoring '%s': %s" % (options.url, e)
            raise
