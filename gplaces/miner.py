from geopy.distance import vincenty, VincentyDistance
from geopy import Point
import async_timeout
import itertools
import asyncio
import aiohttp
import json
import math
from .ptypes import allptypes

HEADERS = {
    'user-agent': ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_5) '
                   'AppleWebKit/537.36 (KHTML, like Gecko) '
                   'Chrome/45.0.2454.101 Safari/537.36'),
}


def url_gen(type, **params_url):
    """Concatenation of latitude/longitude pair, place type, base search url, search radius and API key into a single
    Google Places API query"""

    return "https://maps.googleapis.com/maps/api/place/" + type + "/json?" +\
           "&".join(k + "=" + str(v) for k, v in params_url.items())


def index_get(array, *argv):
    """
    checks if a index is available in the array and returns it
    :param array: the data array
    :param argv: index integers
    :return: None if not available or the return value
    """

    try:
        for index in argv:
            array = array[index]
        return array

    # Value Not Available
    except (IndexError, TypeError, KeyError):
        return None


def get_circle_centers(b1, b2, radius):
    """the function covers the area within the bounds with circles
    this is done by calculating the lat/lng distances and the number of circles needed to fill the area
    as these circles only intersect at one point, an additional grid with a (+radius,+radius) offset is used to
    cover the empty spaces
    :param b1: bounds
    :param b2: bounds
    :param radius: specified radius, adapt for high density areas
    :return: list of circle centers that cover the area between lower/upper
    """

    sw, ne = Point(b1), Point(b2)

    # north/east distances
    dist_lat = int(vincenty(Point(sw[0], sw[1]), Point(ne[0], sw[1])).meters)
    dist_lng = int(vincenty(Point(sw[0], sw[1]), Point(sw[0], ne[1])).meters)

    def cover(p_start, n_lat, n_lng, r):
        _coords = []

        for i in range(n_lat):
            for j in range(n_lng):
                v_north = VincentyDistance(meters=i * r * 2)
                v_east = VincentyDistance(meters=j * r * 2)

                _coords.append(v_north.destination(v_east.destination(point=p_start, bearing=90), bearing=0))

        return _coords

    def _calc_base(dist):
        """ Calculation for base cover """
        return math.ceil((dist - radius) / (2 * radius)) + 1

    def _calc_offset(dist):
        """ Calculation for offset cover """
        return math.ceil((dist - 2 * radius) / (2 * radius)) + 1

    coords = []

    # get circles for base cover
    coords += cover(sw, _calc_base(dist_lat), _calc_base(dist_lng), radius)

    # update south-west for second cover
    vc_radius = VincentyDistance(meters=radius)
    sw = vc_radius.destination(vc_radius.destination(point=sw, bearing=0), bearing=90)

    # get circles for offset cover
    coords += cover(sw, _calc_offset(dist_lat), _calc_offset(dist_lng), radius)

    # only return the coordinates
    return [c[:2] for c in coords]


async def np_fetch(session, np_url, placeapikey):

    await asyncio.sleep(2)
    async with session.get(np_url) as response:
        result = await response.text()
        result = json.loads(result)
        np_url = url_gen("nearbysearch", **{"key": placeapikey, "pagetoken": result["next_page_token"]}) \
            if 'next_page_token' in result else None
        try:
            place_id = [x['place_id'] for x in result['results']]
        except KeyError as e:
            print(e)
            place_id = [result['status'], result['error_message']]
        return place_id, np_url


async def detail_fetch(session, url):
    with async_timeout.timeout(10):
        async with session.get(url) as response:
            return await response.text()


async def new_fetch(session, url, placeapikey):
    """Google Places API request function. Searches each location individually, following a arbitrary number of
    next_page_tokens to extract all place_id values for a given search.
    :param session: Aiohttp Sesson
    :param url: Formulated Google Places API URL
    :param placeapikey: Google Places API key to use in next_page_token searches
    :return results: list of place_id's from page"""

    with async_timeout.timeout(10):
        async with session.get(url) as response:
            result = await response.text()
            result = json.loads(result)
            np_url = url_gen("nearbysearch", **{"key": placeapikey, "pagetoken": result["next_page_token"]}) \
                if 'next_page_token' in result else None
            try:
                results = [x['place_id'] for x in result['results']]
                assert(result['status'] != 'REQUEST_DENIED')
            except AssertionError:
                results = [result['status'], result['error_message']]
            while True:
                if np_url:
                    np_search = asyncio.ensure_future(np_fetch(session, np_url, placeapikey))
                    np_responses = await asyncio.gather(np_search)
                    results += np_responses[0][0]
                    np_url = np_responses[0][1]
                else:
                    break

            return results


async def id_main(loop, id, placeapikey):

    detail_list = []

    async with aiohttp.ClientSession(loop=loop) as session:
        for url in [url_gen("details", **{'placeid': x, 'key': placeapikey}) for x in id]:
            detail_search = asyncio.ensure_future(detail_fetch(session, url))
            detail_list.append(detail_search)
        details = await asyncio.gather(*detail_list)
        details = [json.loads(x) for x in details]
        try:
            #Incorrect API key
            assert 'REQUEST_DENIED' not in [x['status'] for x in details]
        except AssertionError:
            return details[0]
        try:
            #Incorrect ID value
            assert 'INVALID_REQUEST' not in [x['status'] for x in details]
        except AssertionError:
            return [x for x in details if x['status'] == 'INVALID_REQUEST']

    return details


async def area_main(loop, search_url_list, placeapikey, ptype):
    """High level asynchronous function that takes in a list of URLs to be passed to the Google Places API, processing each
    in turn to find paginated results, returning all ID searches to be followed up with detail based searches,
    and then collating the results to be returned.
    :param loop: Asyncio event loop
    :param search_url_list: List of preconstructed Google Places API request URLs
    :param placeapikey: Google Places API key
    :param ptype: Place Type as defined in the ptypes.py file
    :return Google Places Details [place id, formatted address, name, popular_times data, longitude, latitude, type1,
            type2, type3, rating, formatted phone number"""

    ptype = 'allptypes' if ptype == allptypes else ptype[0]

    id_list, detail_list = [], []
    #Search each individual URL and add the returned place id to a list
    async with aiohttp.ClientSession(loop=loop) as session:
        for url in search_url_list:
            new_search = asyncio.ensure_future(new_fetch(session, url, placeapikey))
            id_list.append(new_search)
        responses = await asyncio.gather(*id_list)


        if responses:
            detail_url = [url_gen("details", **{'placeid': x, 'key': placeapikey}) for x in
                          set(list(itertools.chain.from_iterable(responses)))]
            for url in detail_url:
                detail_search = asyncio.ensure_future(detail_fetch(session, url))
                detail_list.append(detail_search)
            details = await asyncio.gather(*detail_list)
            details = [json.loads(x) for x in details]

            return details

        else:
            return responses[0]