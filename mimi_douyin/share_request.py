"""Keep the original shared-post identity across DOM snapshot changes."""


def shared_post_request(peer_key, item):
    return {
        'peer_key': peer_key,
        'message_key': item['key'],
        'message_hint': {
            key: item.get(key)
            for key in ('native_id', 'sender', 'kind', 'links', 'text')
        },
    }
