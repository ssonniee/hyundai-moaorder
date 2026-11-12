"""Platform-neutral payload contract for the future Pleos Android adapter."""
import math


def validate_trip(trip, menu):
    destination = trip['destination']
    if destination['store_id'] != menu['store_id']:
        raise ValueError('Destination and menu store_id differ; load the correct branch menu')
    for data in (destination, trip.get('location')):
        if data is None:
            continue
        for key, limit in [('latitude', 90), ('longitude', 180)]:
            value = data[key]
            if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > limit:
                raise ValueError('Invalid ' + key)
    if not destination.get('name') or not trip.get('session_id'):
        raise ValueError('session_id and destination.name are required')
    return {'sdk': 'NaviHelper', 'operation': 'requestRoute',
            'status': 'pending_android_adapter',
            'route': {key: destination.get(key) for key in
                      ('latitude', 'longitude', 'name', 'poi_id', 'address')},
            'location_source': 'FusedLocation',
            'note': 'This is a command contract, not an executed navigation request.'}
