from .miner import area_main, id_main, asyncio, url_gen, get_circle_centers

import logging
logging.getLogger(__name__).addHandler(logging.NullHandler())

"""

ENTRY POINT

"""


def get_radial(api_key, lat, lng, ptypes, radius):

    url_list = [url_gen("nearbysearch", **{"location": "{0:.6f}".format(lat) + "," + "{0:.6f}".format(lng),
                                  "radius": radius, "type": ptype, "key": api_key}) for ptype in ptypes]
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    response = loop.run_until_complete(area_main(loop, url_list, api_key, ptypes))

    return response


def get_bbox(api_key, ptypes, swbound, nebound, radius):

    url_list = [url_gen("nearbysearch", **{"location": "{0:.6f}".format(lat) + "," + "{0:.6f}".format(lng),
                                  "radius": radius, "type": ptype, "key": api_key})
                for lat, lng, in get_circle_centers(swbound, nebound, radius) for ptype in ptypes]
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    response = loop.run_until_complete(area_main(loop, url_list, api_key, ptypes))

    return response


def get_id(api_key, place_id_list):

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    response = loop.run_until_complete(id_main(loop, place_id_list, api_key))

    return response
