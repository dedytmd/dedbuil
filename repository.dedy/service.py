# -*- coding: UTF-8 -*-

import sys, os
import xbmc, xbmcvfs

if sys.version_info[0] >= 3:
    translatePath = xbmcvfs.translatePath
else:
    translatePath = xbmc.translatePath

if __name__ == '__main__':
    addonfolder = translatePath(os.path.join('special://home/addons', 'plugin.video.dedy'))
    if not os.path.exists(addonfolder):
        xbmc.executebuiltin('InstallAddon(%s)' % ('plugin.video.dedy'))
