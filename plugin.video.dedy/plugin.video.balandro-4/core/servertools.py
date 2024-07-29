# -*- coding: utf-8 -*-

import sys

if sys.version_info[0] >= 3:
    PY3 = True
    unicode = str

    from urllib.parse import urlparse
else:
    PY3 = False

    from urlparse import urlparse    


import os, re, time, datetime

from core import httptools, scrapertools, jsontools, filetools
from core.item import Item
from platformcode import config, logger, platformtools


dict_servers_parameters = {}


def find_video_items(item=None, data=None):
    """
    Función genérica para buscar vídeos en una página, devolviendo un itemlist con los items listos para usar.
     - Si se pasa un Item como argumento, a los items resultantes mantienen los parametros del item pasado
     - Si no se pasa un Item, se crea uno nuevo, pero no contendra ningun parametro mas que los propios del servidor.

    @param item: Item al cual se quieren buscar vídeos, este debe contener la url válida
    @type item: Item
    @param data: Cadena con el contendio de la página ya descargado (si no se pasa item)
    @type data: str

    @return: devuelve el itemlist con los resultados
    @rtype: list
    """

    logger.info()
    itemlist = []

    if data is None and item is None:
        return itemlist

    if data is None:
        data = httptools.downloadpage(item.url).data

    # Crea un item si no hay item
    if item is None:
        item = Item()

    # Busca los enlaces a los videos
    for label, url, server in findvideos(data):
        title = "Enlace encontrado en %s" % label
        itemlist.append(Item(channel=item.channel, action='play', title=title, url=url, server=server))

    return itemlist


# Para un servidor y una url, devuelve la url normalizada según patrones del json
def normalize_url(serverid, url):
    new_url = url # si no se encuentra patrón devolver url tal cual

    server_parameters = get_server_parameters(serverid)
    # Recorre los patrones
    for pattern in server_parameters.get("find_videos", {}).get("patterns", []):
        # Recorre los resultados
        found = False
        if not isinstance(url, str):
            url = (str(url))
        if not PY3 and isinstance(url, unicode):
            url = url.encode('utf-8', 'strict')
        elif PY3 and isinstance(url, bytes):
            url = url.decode('utf-8', 'strict')

        for match in re.compile(pattern["pattern"], re.DOTALL).finditer(url):
            new_url = pattern["url"]

            for x in range(len(match.groups())):
                new_url = new_url.replace("\\%s" % (x + 1), match.groups()[x])

            ignore_urls = server_parameters["find_videos"].get("ignore_urls", [])

            if new_url not in ignore_urls:
                if str(ignore_urls) == "['https://vk.com/video']" or str(ignore_urls) == "['https://vtbe.to']":
                    new_url = url

                found = True
            else:
                new_url = url
            break

        if found: break

    return new_url


def get_servers_itemlist(itemlist):
    """
    Obtiene el servidor para cada uno de los items, en funcion de su url.
     - Asigna el servidor y la url modificada.
     - Si no se encuentra servidor para una url, se asigna "directo"
    """

    # Recorre los servidores
    for serverid in get_servers_list().keys():
        server_parameters = get_server_parameters(serverid)

        if server_parameters.get("active") == False: continue

        # Recorre los patrones
        for pattern in server_parameters.get("find_videos", {}).get("patterns", []):
            # Recorre los resultados
            for match in re.compile(pattern["pattern"], re.DOTALL).finditer("\n".join([item.url.split('|')[0] for item in itemlist if not item.server])):
                url = pattern["url"]
                for x in range(len(match.groups())):
                    url = url.replace("\\%s" % (x + 1), match.groups()[x])

                for item in itemlist:
                    if match.group() in item.url:
                        item.server = serverid
                        if '|' in item.url:
                            item.url = url + '|' + item.url.split('|')[1]
                        else:
                            item.url = url

    for item in itemlist:
        if not item.server and item.url: # Si no se ha encontrado server
            item.server = "desconocido" #"directo"

    return itemlist


def findvideos(data, skip=False, disabled_servers=False):
    """
    Recorre la lista de servidores disponibles y ejecuta la funcion findvideosbyserver para cada uno de ellos
    :param data: Texto donde buscar los enlaces
    :param skip: Indica un limite para dejar de recorrer la lista de servidores. Puede ser un booleano en cuyo caso
    seria False para recorrer toda la lista (valor por defecto) o True para detenerse tras el primer servidor que
    retorne algun enlace. Tambien puede ser un entero mayor de 1, que representaria el numero maximo de enlaces a buscar.
    :return:
    """

    logger.info()
    devuelve = []

    skip = int(skip)
    servers_list = get_servers_list().keys()

    # Ejecuta el findvideos en cada servidor activo
    for serverid in servers_list:
        if not disabled_servers and not is_server_enabled(serverid):
            continue

        devuelve.extend(findvideosbyserver(data, serverid, disabled_servers=disabled_servers))
        if skip and len(devuelve) >= skip:
            devuelve = devuelve[:skip]
            break

    return devuelve


def findvideosbyserver(data, serverid, disabled_servers=False):
    devuelve = []

    serverid = get_server_id(serverid)
    if not disabled_servers and not is_server_enabled(serverid):
        return devuelve

    server_parameters = get_server_parameters(serverid)
    if "find_videos" in server_parameters:
        # Recorre los patrones
        for pattern in server_parameters["find_videos"].get("patterns", []):
            msg = "%s\npattern: %s" % (serverid, pattern["pattern"])
            # Recorre los resultados
            if not isinstance(data, str):
                data = (str(data))
            if not PY3 and isinstance(data, unicode):
                data = data.encode('utf-8', 'strict')
            elif PY3 and isinstance(data, bytes):
                data = data.decode('utf-8', 'strict')

            for match in re.compile(pattern["pattern"], re.DOTALL).finditer(data):
                url = pattern["url"]
                # Crea la url con los datos
                for x in range(len(match.groups())):
                    url = url.replace("\\%s" % (x + 1), match.groups()[x])

                value = server_parameters["name"], url, serverid
                if value not in devuelve and url not in server_parameters["find_videos"].get("ignore_urls", []):
                    devuelve.append(value)

                msg += "\nurl encontrada: %s" % url
                logger.info(msg)

    return devuelve


# Por defecto no se tienen en cuenta los servidores desactivados y se devuelve 'directo' si no se encuentra.
# Con disabled_servers=True se detectan tb los desactivados y se devuelve None si no se encuentra.
def get_server_from_url(url, disabled_servers=False):
    encontrado = findvideos(url, skip=True, disabled_servers=disabled_servers)

    if len(encontrado) > 0:
        return encontrado[0][2]
    else:
        if not disabled_servers:
            return 'directo' # No devuelve desconocido pq puede que sea un "conocido" que esté desactivado
        else:
            return None


# Para un servidor y una url, devuelve video_urls ([]), puede (True/False), motivo_no_puede
def resolve_video_urls_for_playing(server, url, url_referer=''):
    video_urls = []

    logger.info("Server: %s, Url: %s" % (server, url))

    server = get_server_id(server) # por si hay servers con múltiples ids

    # Si el vídeo es "directo" o "local", no hay que buscar más
    if server == "directo" or server == "local":
        video_urls.append(["%s [%s]" % (urlparse(url)[2][-4:], server), url])

    else:
        # Parámetros json del server
        server_parameters = get_server_parameters(server) if server else {}
        server_name = server_parameters['name'] if 'name' in server_parameters else server.capitalize()

        if 'active' not in server_parameters:
            errmsg = 'Falta conector del servidor %s' % server_name
            logger.error(errmsg)
            return [], False, errmsg

        if server_parameters['active'] == False:
            errmsg = 'Conector del servidor %s está desactivado' % server_name
            if 'notes' in server_parameters: errmsg += '. ' + server_parameters['notes']
            logger.debug(errmsg)
            return [], False, errmsg

        # Importa el server
        try:
            server_module = __import__('servers.%s' % server, None, None, ["servers.%s" % server])
        except:
            errmsg = 'No se pudo importar el servidor %s' % server_name
            logger.error(errmsg)
            import traceback
            logger.error(traceback.format_exc())
            return [], False, errmsg

        # Llama a get_video_url() del server
        try:
            response = server_module.get_video_url(page_url=url, url_referer=url_referer)
            if not isinstance(response, list):
                return [], False, '[%s] %s' % (server_name, response)
            elif len(response) > 0:
                video_urls.extend(response)
        except:
            errmsg = 'Error inesperado en el servidor %s' % server_name
            logger.error(errmsg)
            import traceback
            logger.error(traceback.format_exc())
            return [], False, errmsg

        if len(video_urls) == 0:
            return [], False, 'Vídeo No localizado en %s' % server_name

    return video_urls, True, ''


# Para servers con varios ids, busca si es uno de los ids alternativos y devuelve el id principal
def get_server_id(serverid):
    # A mano para evitar recorrer todos los servidores !? (buscar "more_ids" en los json de servidores)
    return corregir_servidor(serverid)

    serverid = serverid.lower()

    # Obtenemos el listado de servers
    server_list = get_servers_list().keys()

    # Si el nombre está en la lista
    if serverid in server_list:
        return serverid

    # Recorre todos los servers buscando el nombre alternativo
    for server in server_list:
        params = get_server_parameters(server)
        if 'more_ids' not in params:
            continue
        if serverid in params['more_ids']:
            return server

    return '' # Si no se encuentra nada se devuelve una cadena vacia


def is_server_enabled(server):
    """
    Función comprobar si un servidor está segun la configuración establecida
    @param server: Nombre del servidor
    @type server: str

    @return: resultado de la comprobación
    @rtype: bool
    """

    server_parameters = get_server_parameters(server)

    if 'active' not in server_parameters or server_parameters['active'] == False:
        return False

    return config.get_setting('status', server=server, default=0) >= 0


def is_server_available(server):
    """
    Función comprobar si existe el json de un servidor
    @param server: Nombre del servidor
    @type server: str

    @return: resultado de la comprobación
    @rtype: bool
    """

    path = os.path.join(config.get_runtime_path(), 'servers', server + '.json')
    return os.path.isfile(path)


def get_server_parameters(server):
    """
    Obtiene los datos del servidor
    @param server: Nombre del servidor
    @type server: str

    @return: datos del servidor
    @rtype: dict
    """

    global dict_servers_parameters

    if server not in dict_servers_parameters:
        try:
            if server == 'desconocido': 
                dict_server = {'active': False, 'id': 'desconocido', 'name': 'Desconocido'}
                dict_servers_parameters[server] = dict_server
                return dict_server

            path = os.path.join(config.get_runtime_path(), 'servers', server + '.json')
            if not os.path.isfile(path):
                logger.info('Falta el .json del servidor: %s' % server)
                return {}

            data = filetools.read(path)
            dict_server = jsontools.load(data)

            # valores por defecto si no existen:
            dict_server['active'] = dict_server.get('active', False)
            if 'find_videos' in dict_server:
                dict_server['find_videos']['patterns'] = dict_server['find_videos'].get('patterns', list())
                dict_server['find_videos']['ignore_urls'] = dict_server['find_videos'].get('ignore_urls', list())

            dict_servers_parameters[server] = dict_server

        except:
            mensaje = "Error carga .json del servidor: %s\n" % server
            import traceback
            logger.error(mensaje + traceback.format_exc())
            return {}

    return dict_servers_parameters[server]


def get_server_setting(name, server, default=None):
    config.get_setting('server_' + server + '_' + name, default=default)
    return value

def set_server_setting(name, value, server):
    config.set_setting('server_' + server + '_' + name, value)
    return value


def get_servers_list():
    """
    Obtiene un diccionario con todos los servidores disponibles

    @return: Diccionario cuyas claves son los nombre de los servidores (nombre del json)
    y como valor un diccionario con los parametros del servidor.
    @rtype: dict
    """

    server_list = {}
    for server in os.listdir(os.path.join(config.get_runtime_path(), 'servers')):
        if server.endswith('.json'):
            serverid = server.replace('.json', '')
            server_parameters = get_server_parameters(serverid)
            if server_parameters['id'] != serverid:
                logger.error('El id: %s no coincide con el servidor %s' % (server_parameters['id'], serverid))
                continue
            server_list[serverid] = server_parameters # devolver aunque no esté activo para poder detectar sus patrones.

    return server_list


# Normalizar nombre del servidor (para los canales que no lo obtienen de los patrones, y para evitar bucle more_ids en get_server_id())
def corregir_servidor(servidor):
    servidor = servidor.strip().lower()

    if servidor in ['netuplayer', 'netutv', 'waaw1', 'waaws', 'waaw', 'netu', 'hqq', 'megavideo', 'megaplay', 'vidxhot', 'player.moovies.in', 'richhioon', 'woffxxx', 'pornjustx', 'doplay', 'younetu', 'stbnetu', 'ncdn22', 'oyohd']: return 'waaw'
    # ~ if servidor in ['netutv', 'waaw1', 'waaws', 'waaw', 'netu', 'hqq', 'megavideo', 'megaplay', 'vidxhot', 'player.moovies.in', 'richhioon', 'woffxxx', 'pornjustx']: return 'netutv'

    elif servidor in ['powvideo', 'povwideo', 'powvldeo', 'powv1deo', 'povw1deo']: return 'powvideo'
    elif servidor in ['streamplay', 'steamplay', 'streamp1ay']: return 'streamplay'

    # ~ elif servidor in ['fembed', 'fembed-hd', 'fembeder', 'divload', 'ilovefembed', 'myurlshort', 'jplayer', 'feurl', 'fembedisthebest', 'femax20', 'fcdn', 'fembad', 'pelispng', 'hlshd', 'embedsito', 'mrdhan', 'dutrag', 'fplayer', 'diasfem', 'suzihaza', 'vanfem', 'youtvgratis', 'oceanplay', 'gotovideo.kiev.ua', 'owodeuwu', 'sypl', 'fembed9hd', 'watchse', 'vcdn', 'femoload', 'cubeembed']: return 'fembed'

    elif servidor in ['evoplay']: return 'evoload'
    elif servidor in ['streamta.pe', 'strtapeadblock', 'strtapeadblocker', 'streamtapeadblock', 'streamadblockplus', 'adblockstrtech', 'adblockstrtape', 'adblockstreamtape', 'adblockeronstape', 'playstp', 'strcloud', 'strtpe', 'stape', 'strtape', 'scloud', 'shavetape', 'stapewithadblock', 'streamtapeadblockuser', 'stapadblockuser', 'adblocktape', 'streamta.site', 'streamadblocker', 'stp', 'tapewithadblock.org', 'adblocktape.wiki', 'antiadtape.com', 'tapeblocker.com', 'streamnoads.com']: return 'streamtape'

    # ~ elif servidor in ['sbembed', 'sbembed1', 'sbembed2', 'sbvideo', 'japopav']: return 'sbembed'

    elif servidor in ['streams1', 'streams2']: return 'streams3'

    # ~ elif servidor in ['sbplay', 'sbplay1', 'sbplay2', 'pelistop', 'sbfast', 'sbfull', 'ssbstream', 'sbthe', 'sbspeed', 'cloudemb', 'tubesb', 'embedsb', 'playersb', 'sbcloud1', 'watchsb', 'viewsb', 'watchmo', 'streamsss', 'sblanh', 'sbanh', 'sblongvu', 'sbchill', 'sbrity', 'sbhight', 'sbbrisk', 'sbface', 'view345', 'sbone', 'sbasian', 'streaamss', 'lvturbo', 'sbnet', 'sbani', 'sbrapid', 'cinestart', 'vidmoviesb', 'sbsonic', 'sblona', 'likessb']: return 'streamsb'

    elif servidor in ['slmaxed', 'sltube', 'slwatch']: return 'streamlare'
    elif servidor in ['streamhide', 'playhide', 'guccihide', 'moviesm4u', 'louishide', 'ahvsh', 'movhide']: return 'streamhide'

    elif servidor in ['highload', 'streamon']: return 'highload'
    elif servidor in ['vupload']: return 'vup'
    elif servidor in ['hdvid', 'vidhdthe']: return 'vidhd'
    elif servidor in ['vtube', 'vidhdthe', 'vtplay', 'vtbe']: return 'playtube'
    elif servidor in ['voesx', 'voe-', 'voeun', '-voe', 'reputationsheriffkennethsand', 'fittingcentermondaysunday.com', 'tinycat-voe-fashion.com', 'scatch176duplicities.com', 'voex', 'yodelswartlike', 'nectareousoverelate', 'apinchcaseation', 'strawberriesporail', 'crownmakermacaronicism', 'cigarlessarefy', 'generatesnitrosate', 'figeterpiazine', 'timberwoodanotia', 'tubelessceliolymph', 'wolfdyslectic', 'metagnathtuggers', 'chromotypic', 'gamoneinterrupted', 'rationalityaloelike', 'valeronevijao', 'availedsmallest', 'prefulfilloverdoor', 'jayservicestuff', 'brookethoughi', 'jasonresponsemeasure', 'graceaddresscommunity']: return 'voe'

    elif servidor in ['dai.ly']: return 'dailymotion'
    elif servidor in ['ploud', 'midov']: return 'peertube'
    elif servidor in ['videoloca', 'tnaket', 'makaveli']: return 'upvideo'

    elif servidor in ['chouhaa']: return 'youwatch'
    elif servidor in ['mega.nz']: return 'mega'
    elif servidor in ['gloria.tv']: return 'gloria'
    elif servidor in ['vev.io']: return 'vevio'
    elif servidor in ['gvideo', 'google', 'google drive', 'gdrive', 'drive.google', 'drive']: return 'gvideo'
    elif servidor in ['mailru', 'my.mail', 'my.mail.ru', 'my', 'mail', 'mail.ru']: return 'mailru'

    elif servidor in ['vidtodo', 'vidto', 'vidtodoo', 'vixtodo']: return 'vidtodo'
    elif servidor in ['okru', 'ok.ru', 'ok-ru', 'ok server', 'okru.link', 'odnoklassniki', 'okrufer', 'ok']: return 'okru'
    elif servidor in ['streamz', 'streamzz']: return 'streamz'
    elif servidor in ['vevio', 'vev']: return 'vevio'
    elif servidor in ['vsmobi', 'v-s']: return 'vsmobi'
    elif servidor in ['doodstream', 'dood', 'dooood', 'ds2play', 'doods', 'ds2video', 'd0o0d', 'do0od', 'd0000d', 'd000d']: return 'doodstream'
    elif servidor in ['archiveorg', 'archive.org', 'archive']: return 'archiveorg'
    elif servidor in ['youtube', 'youtu']: return 'youtube'
    elif servidor in ['mp4upload', 'mp4up']: return 'mp4upload'
    elif servidor in ['yourupload', 'yourup']: return 'yourupload'
    elif servidor in ['verystream', 'verys']: return 'verystream'
    elif servidor in ['flix555', 'flix']: return 'flix555'
    elif servidor in ['byter', 'biter']: return 'byter'
    elif servidor in ['thevideome', 'thevideo']: return 'thevideome'
    elif servidor in ['1fichier', 'onefichier']: return '1fichier'
    elif servidor in ['uploadedto', 'uploaded', 'ul', 'ul.to']: return 'uploadedto'
    elif servidor in ['pixel']: return 'pixeldrain'
    elif servidor in ['clickndownload']: return 'clicknupload'
    elif servidor in ['mixdrop', 'mixdroop', 'mixdrp', 'mdy48tn97', 'md3b0j6hj', 'mdbekjwqa', 'mdfx9dc8n', 'mdzsmutpcvykb']: return 'mixdrop'
    elif servidor in ['vidoza', 'videzz']: return 'vidoza'

    elif servidor == 'uptostream': return 'uptobox'

    elif servidor in ['tubeload', 'mvidoo', 'rutube', 'filemoon', 'moonplayer', 'streamhub', 'uploadever', 'videowood', 'yandex', 'yadi.', 'fastupload', 'dropload', 'streamwish', 'krakenfiles', 'hexupload', 'hexload', 'desiupload', 'filelions', 'youdbox', 'yodbox', 'youdboox', 'vudeo', 'embedgram', 'embedrise', 'embedwish', 'wishembed', 'vidguard', 'vgfplay', 'v6embed', 'vgembed', 'vembed', 'vid-guard', 'strwish', 'azipcdn', 'awish', 'dwish', 'mwish', 'swish', 'lulustream', 'luluvdo', 'lion', 'alions', 'dlions', 'mlions', 'turboviplay', 'emturbovid', 'tuborstb', 'streamvid' 'upload.do', 'uploaddo', 'file-upload', 'wishfast', 'doodporn', 'vidello', 'vidspeed', 'sfastwish', 'fviplions', 'moonmov', 'flaswish', 'vkspeed', 'vkspeed7', 'obeywish', 'twitch', 'vidhide', 'hxfile', 'drop', 'embedv', 'vgplayer', 'userload', 'uploadraja', 'cdnwish', 'goodstream', 'asnwish', 'flastwish', 'jodwish', 'fmoonembed', 'embedmoon', 'moonjscdn', 'rumble', 'bembed', 'javlion', 'streamruby', 'sruby', 'rubystream', 'stmruby', 'rubystm', 'swhoi', 'listeamed', 'fsdcmo', 'fdewsdc', 'qiwi', 'swdyu', 'ponmi']: return 'various'

    elif servidor in ['allviid', 'cloudfile', 'cloudmail', 'dailyuploads', 'darkibox', 'dembed', 'downace', 'fastdrive', 'fastplay', 'filegram', 'gostream', 'letsupload', 'liivideo', 'myupload', 'oneupload', 'pandafiles', 'rovideo', 'send', 'streamable', 'streamdav', 'streamgzzz', 'streamoupload', 'tusfiles', 'uploadba', 'uploadflix', 'uploady', 'veev', 'veoh', 'vidbob', 'vidlook', 'vidmx', 'vid', 'vidpro', 'vidstore', 'vipss', 'vkprime', 'worlduploads', 'ztreamhub', 'amdahost']: return 'zures'

    else: return servidor


def corregir_other(srv):
    srv = srv.lower().strip()

    if 'tubeload' in srv: srv = 'Tubeload'
    elif 'mvidoo' in srv: srv = 'Mvidoo'
    elif 'rutube' in srv: srv = 'Rutube'
    elif 'videowood' in srv: srv = 'Videowood'
    elif 'yandex' in srv: srv = 'Yandex'
    elif 'fastupload' in srv: srv = 'Fastupload'
    elif 'dropload' in srv: srv = 'Dropload'
    elif 'krakenfiles' in srv: srv = 'Krakenfiles'

    elif 'hexupload' in srv or 'hexload' in srv: srv = 'Hexupload'

    elif 'embedgram' in srv: srv = 'Embedgram'
    elif 'embedrise' in srv: srv = 'Embedrise'
    elif 'streamvid' in srv: srv = 'Streamvid'

    elif 'upload.do' in srv or 'uploaddo' in srv: srv = 'Upload'

    elif 'filemoon' in srv or 'fmoonembed' in srv or 'embedmoon' in srv or 'moonjscdn' in srv: srv = 'Filemoon'
    elif 'streamhub' in srv: srv = 'Streamhub'
    elif 'uploadever' in srv: srv = 'Uploadever'
    elif 'moonmov' in srv: srv = 'Moonplayer'
    elif 'moonplayer' in srv: srv = 'Moonplayer'
    elif 'yadi' in srv: srv = 'Yandex'

    elif 'streamwish' in srv or 'strwish' in srv or 'embedwish' in srv or 'wishembed' in srv or 'awish' in srv or 'dwish' in srv or 'mwish' in srv or 'wishfast' in srv or 'doodporn' in srv or 'sfastwish' in srv or 'flaswish' in srv or 'obeywish' in srv or 'cdnwish' in srv or 'asnwish' in srv or 'flastwish' in srv or 'jodwish' in srv or 'swhoi' in srv or 'fsdcmo' in srv or 'swdyu' in srv: srv = 'Streamwish'

    elif 'desiupload' in srv: srv = 'Desiupload'

    elif 'filelions' in srv or 'azipcdn' in srv or 'alions' in srv or 'dlions' in srv or 'mlions' in srv or 'lion' in srv or 'fviplions' in srv or 'javlion' in srv or 'fdewsdc' in srv: srv = 'Filelions'

    elif 'youdbox' in srv or 'yodbox' in srv or 'youdboox' in srv: srv = 'Youdbox'

    elif 'vudeo' in srv: srv = 'Vudeo'

    elif 'vidguard' in srv or 'vgfplay' in srv or 'vgembed' in srv or 'v6embed' in srv or 'vembed' in srv or 'vid-guard' in srv or 'embedv' in srv or 'vgplayer' in srv or 'bembed' in srv or 'listeamed' in srv : srv = 'Vidguard'

    elif 'lulustream' in srv or 'luluvdo' in srv or 'ponmi' in srv: srv = 'Lulustream'

    elif 'turboviplay' in srv or 'emturbovid' in srv or 'tuborstb' in srv: srv = 'Turboviplay'

    elif 'file-upload' in srv: srv = 'Fileupload'

    elif 'vidello' in srv: srv = 'Vidello'

    elif 'vidspeed' in srv or 'vidspeeds' in srv: srv = 'Vidspeed'

    elif 'vkspeed' in srv or 'vkspeed7' in srv: srv = 'Vkspeed'

    elif 'twitch' in srv: srv = 'Twitch'

    elif 'vidhide' in srv: srv = 'Vidhidepro'

    elif 'hxfile' in srv: srv = 'Hxfile'

    elif 'drop' in srv: srv = 'Drop'

    elif 'userload' in srv: srv = 'Userload'

    elif 'uploadraja' in srv: srv = 'Uploadraja'

    elif 'goodstream' in srv: srv = 'Goodstream'

    elif 'rumble' in srv: srv = 'Rumble'

    elif 'qiwi' in srv: srv = 'Qiwi'

    elif 'streamruby' in srv or 'sruby' in srv or 'rubystream' in srv or 'stmruby' in srv or 'rubystm' in srv: srv = 'Streamruby'

    elif 'allviid' in srv or 'cloudfile' in srv or 'cloudmail' in srv or 'dailyuploads' in srv or 'darkibox' in srv or 'dembed' in srv or 'downace' in srv or 'fastdrive' in srv or 'fastplay' in srv or 'filegram' in srv or 'gostream' in srv or 'letsupload' in srv or 'liivideo' in srv or 'myupload' in srv or 'oneupload' in srv or 'pandafiles' in srv or 'rovideo' in srv or 'send' in srv or 'streamable' in srv or 'streamdav' in srv or 'streamgzzz' in srv or 'streamoupload' in srv or 'tusfiles' in srv or 'uploadba' in srv or 'uploadflix' in srv or 'uploady' in srv or 'veev' in srv or 'veoh' in srv or 'vidbob' in srv or 'vidlook' in srv or 'vidmx' in srv or 'vid' in srv or 'vidpro' in srv or 'vipss' in srv or 'vkprime' in srv or 'worlduploads' in srv or 'ztreamhub' in srv or 'amdahost' in srv: srv = 'Zures'

    return srv


# Reordenación/Filtrado de enlaces
def filter_and_sort_by_quality(itemlist):
    servers_sort_quality = config.get_setting('servers_sort_quality', default=0) # 0: orden web, 1: calidad desc, 2: calidad asc

    # Ordenar por preferencia de calidades
    logger.info('Preferencias orden calidades: %s' % servers_sort_quality)
    
    if servers_sort_quality == 1:
        return sorted(itemlist, key=lambda it: it.quality_num, reverse=True)
    elif servers_sort_quality == 2:
        return sorted(itemlist, key=lambda it: it.quality_num)
    else:
        return itemlist


def filter_and_sort_by_server(itemlist):
    # not it.server para casos en que no está definido y se resuelve en el play del canal

    # Quitar enlaces de servidores descartados por el usuario
    servers_discarded = config.get_setting('servers_discarded', default='')
    if servers_discarded != '':
        servers_discarded_list = servers_discarded.lower().replace(' ', '').split(',')
        logger.info('Servidores descartados usuario: %s' % ', '.join(servers_discarded_list))
        itemlist = filter(lambda it: (not it.server and 'indeterminado' not in servers_discarded_list) or (it.server and it.server.lower() not in servers_discarded_list), itemlist)

    # Ordenar enlaces de servidores preferidos del usuario
    servers_preferred = config.get_setting('servers_preferred', default='')
    servers_unfavored = config.get_setting('servers_unfavored', default='')
    if servers_preferred != '' or servers_unfavored != '':
        servers_preferred_list = servers_preferred.lower().replace(' ', '').split(',')
        servers_unfavored_list = servers_unfavored.lower().replace(' ', '').split(',')
        if servers_preferred != '': logger.info('Servidores preferentes usuario: %s' % ', '.join(servers_preferred_list))
        if servers_unfavored != '': logger.info('Servidores última opción usuario: %s' % ', '.join(servers_unfavored_list))

        def numera_server(servidor):
            if not servidor: servidor = 'indeterminado'
            if servidor in servers_preferred_list:
                return servers_preferred_list.index(servidor)
            elif servidor in servers_unfavored_list:
                return 999 - servers_unfavored_list.index(servidor)
            else: 
                return 99

        itemlist = sorted(itemlist, key=lambda it: numera_server(it.server.lower()))

    # Quitar enlaces de servidores inactivos
    return filter(lambda it: not it.server or is_server_enabled(get_server_id(it.server)), itemlist)


def get_lang(lang):
    if not lang: return '?'
    if lang in ['Esp','Lat']: return lang
    return 'VO'


def filter_and_sort_by_language(itemlist):
    # prefs = {'Esp': pref_esp, 'Lat': pref_lat, 'VO': pref_vos} dónde pref_xxx "0:Descartar|1:Primero|2:Segundo|3:Tercero"

    # Quitar enlaces de idiomas descartados y ordenar por preferencia de idioma
    prefs = config.get_lang_preferences()
    logger.info('Preferencias idioma servidores: %s' % str(prefs))
    prefs['?'] = 4 # Cuando no hay idioma mostrar al final

    itemlist = filter(lambda it: prefs[get_lang(it.language)] != 0, itemlist)

    return sorted(itemlist, key=lambda it: prefs[get_lang(it.language)])


def get_parse_hls(video_urls):
    logger.info()

    import codecs

    hs = ''
    new_video_urls = list()
    headers = dict()

    if not video_urls:
        return 'Falta el Archivo.'

    if not (len(video_urls)) == 1:
        return 'Archivo Múltiple No soportado.'

    url = video_urls[0][1]
    if '|' in url:
        part = url.split('|')
        url = part[0]

        if not url.endswith('blenditall.m3u8'):
            if not 'master.m3u8' in url:
                return 'Tipo de Archivo desconocido.'

        khs = part[1]
        hs = '|' + khs

        matches = scrapertools.find_multiple_matches(khs, r'(\w+)=([^&]+)')

        for key, val in matches:
            headers[key] = val

    if not url.endswith('blenditall.m3u8'):
        if not 'master.m3u8' in url:
            return 'Tipo de Archivo desconocido.'

    headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; rv:109.0) Gecko/20100101 Firefox/115.0'
    headers['Accept'] = '/'
    headers['Accept-Encoding'] = 'gzip, deflate, br, zstd'

    # ~ headers['Accept-Language'] = 'es-ES,es;q=0.9,en;q=0.8,gl;q=0.7,ca;q=0.6,ru;q=0.5'

    headers['Connection'] = 'keep-alive'
    headers['Origin'] = 'https://fastream.to'
    headers['Referer'] = 'https://fastream.to/'

    data = httptools.downloadpage(url, headers=headers).data

    if not isinstance(data, str):
        datos = data
        try: data = codecs.decode(data, 'utf-8', 'strict')
        except: data = datos

    if '<h1>403 Forbidden</h1>' in data:
        return 'Acceso al Archivo denegado.'

    matches = scrapertools.find_multiple_matches(data, r'#EXT-X-STREAM-INF.*?RESOLUTION=(\d+x\d+).*?\s(http.*?)\s')
    if not matches:
        patron = 'RESOLUTION=\d+x(\d+),.*?'
        patron += 'URI="([^"]+)"'

        matches = re.compile(patron, re.DOTALL).findall(data)

    sub_server = ''
    if 'master.m3u8' in url:
        sub_server = scrapertools.find_single_match(url, "(.*?)master.m3u8")

    if len(matches) > 1:
        for res, video_url in matches:
            if sub_server: video_url = sub_server + video_url

            video_url += hs
            video_url = video_url.replace('iframes', 'index')

            info = '.m3u8 (%s)' % res
            new_video_urls.append([info, video_url])

        return new_video_urls

    return video_urls
