import jmespath
import demistomock as demisto
from CommonServerPython import *
from JSONFeedApiModule import *  # noqa: E402
from typing import Dict

DEFAULT_COUNT = 100
SEARCH_PARAMS = {
    'indicator': 'indicator',
    'from': 'from',
    'until': 'until',
    'threat_type': 'threatType',
    'malware_family': 'malwareFamily',
    'confidence': 'confidence',
    'count': 'count',
}
FEED_INDICATOR_TYPES = {
    FeedIndicatorType.URL: FeedIndicatorType.URL,
    FeedIndicatorType.File: FeedIndicatorType.File,
    "ipv4": FeedIndicatorType.IP
}
FEED_URL = 'https://api.intel471.com/v1/indicators/stream?'
MAPPING = {
    FeedIndicatorType.File: {
        'threat_type': 'threattypes.threatcategory',
        'threat_data_family': 'malwarefamily',
        'indicator_data_file_md5': 'md5',
        'indicator_data_file_sha1': 'sha1',
        'indicator_data_file_sha256': 'sha256',
        'context_description': 'description',
        'indicator_data_file_download_url': 'downloadurl',
        'mitre_tactics': 'mitretactics',
        'relation_entity_b': 'threat_data_family'
    },
    FeedIndicatorType.URL: {'threat_type': 'threattypes.threatcategory',
                            'threat_data_family': 'malwarefamily',
                            'indicator_data_url': 'url',
                            'context_description': 'description',
                            'mitre_tactics': 'mitretactics',
                            'relation_entity_b': 'threat_data_family'
                            },
    "ipv4": {'threat_type': 'threattypes.threatcategory',
             'threat_data_family': 'malwarefamily',
             'indicator_data_address': 'ipaddress',
             'context_description': 'description',
             'mitre_tactics': 'mitretactics',
             'relation_entity_b': 'threat_data_family'
             }
}
INDICATOR_VALUE_FIELD = {FeedIndicatorType.File: 'indicator_data_file_sha256',
                         FeedIndicatorType.URL: 'indicator_data_url',
                         "ipv4": 'indicator_data_address'}


def _create_url(**kwargs):
    url_suffix = ""
    for param in kwargs:
        url_suffix += f"&{param}={kwargs.get(param)}"
    return FEED_URL + url_suffix.strip('&')


def _build_url_parameter_dict(**kwargs):
    """
    Given a set of parameters, creates a dictionary with only searchable items that can be used in api.
    """
    params_dict = {}
    for param in kwargs:
        if param in SEARCH_PARAMS:
            params_dict[SEARCH_PARAMS.get(param)] = kwargs.get(param)
    return params_dict


def get_params_by_indicator_type(**kwargs):
    indicators_url = {}
    params = _build_url_parameter_dict(**kwargs)
    params['count'] = int(params.get('count', DEFAULT_COUNT))

    indicator_types = argToList(kwargs.get('indicator_type'))

    # allows user to choose multiple indicator types at once.
    if 'All' in indicator_types:
        indicator_types = FEED_INDICATOR_TYPES

    for current_type in indicator_types:
        params['indicatorType'] = current_type
        indicators_url[current_type] = _create_url(**params)
    return indicators_url


def custom_build_iterator(client: Client, feed: Dict, limit: int = 0, **kwargs) -> List:
    url = feed.get('url', client.url)
    fetch_time = feed.get('fetch_time')
    start_date, end_date = parse_date_range(fetch_time, utc=True, to_timestamp=True)
    integration_context = get_integration_context()
    last_fetch = integration_context.get(f"{feed.get('indicator_type')}_fetch_time")
    params = {'lastUpdatedFrom': last_fetch if last_fetch else start_date}
    result: List[Dict] = []
    should_continue = True

    while should_continue:
        r = requests.get(
            url=url,
            verify=client.verify,
            auth=client.auth,
            cert=client.cert,
            headers=client.headers,
            params=params,
            **kwargs
        )
        try:
            r.raise_for_status()
            data = r.json()
            current_result = jmespath.search(expression=feed.get('extractor'), data=data)
            if current_result:
                result = result + current_result

            # gets next page reference and handles paging.
            should_continue = len(result) < limit if result else True
            should_continue = should_continue or data.get('cursorNext') != params.get('cursor')
            params['cursor'] = data.get('cursorNext') if should_continue else ''

        except ValueError as VE:
            raise ValueError(f'Could not parse returned data to Json. \n\nError massage: {VE}')

    set_integration_context({f"{feed.get('indicator_type')}_fetch_time": str(end_date)})
    return result


def custom_build_relationships(feed_config: dict, mapping: dict, indicator_data: dict):
    if indicator_data.get(mapping.get('relation_entity_b')):
        relationships_lst = EntityRelationship(
            name=feed_config.get('relation_name'),
            entity_a=indicator_data.get('value'),
            entity_a_type=indicator_data.get('type'),
            entity_b=indicator_data.get(mapping.get('relation_entity_b')),
            entity_b_type=feed_config.get('relation_entity_b_type'),
        )
        return [relationships_lst.to_indicator()]


def main():
    params = {k: v for k, v in demisto.params().items() if v is not None}
    urls = get_params_by_indicator_type(**params)
    params['feed_name_to_config'] = {}
    for indicator_type in urls:
        params['feed_name_to_config'][indicator_type] = {
            'url': urls.get(indicator_type),
            'extractor': 'indicators[*].data',
            'indicator_type': FEED_INDICATOR_TYPES.get(indicator_type),
            'indicator': INDICATOR_VALUE_FIELD.get(indicator_type),
            'flat_json_with_prefix': True,
            'mapping': MAPPING.get(indicator_type),
            'custom_build_iterator': custom_build_iterator,
            'fetch_time': params.get('fetch_time', '7 days'),
            'relation_entity_b_type': 'STIX Malware',
            'relation_name': EntityRelationship.Relationships.COMMUNICATES_WITH,
            'create_relations_function': custom_build_relationships,

        }
    feed_main(params, 'Intel471 Indicators Feed', 'intel471-indicators')


if __name__ in ('__main__', '__builtin__', 'builtins'):
    main()
