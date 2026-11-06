// Both the conversation list and the open chat must resolve to the same key.
// Keep legacy keys so existing allowlists, sessions and memory links stay valid.
export class ConversationIdentities {
  constructor(hash, publicURL, known = {}, legacyKeys = []) {
    this.hash = hash;
    this.publicURL = publicURL;
    this.known = new Map(Object.entries(known));
    this.legacyKeys = new Set(legacyKeys);
    this.dirty = false;
  }

  id(peer) {
    const group = peer.conversation_type === 'group' || peer.conversation_type === 2;
    return peer.conversation_id ? (group ? 'group:' : 'private:') + peer.conversation_id : '';
  }

  remember(peer, key) {
    const id = this.id(peer);
    if (id && key && this.known.get(id) !== key) {
      this.known.set(id, key);
      this.dirty = true;
    }
  }

  key(peer) {
    const id = this.id(peer);
    if (id && this.known.has(id)) return this.known.get(id);
    const group = peer.conversation_type === 'group' || peer.conversation_type === 2;
    if (group) return peer.conversation_id ? this.hash('group:' + peer.conversation_id) : '';
    const link = this.publicURL(peer.link);
    const fallback = peer.name && peer.avatar ? peer.name + '|' + this.publicURL(peer.avatar) : '';
    // A legacy key is accepted only when the current DOM supplies its identity.
    for (const identity of [link, peer.conversation_id, fallback]) {
      if (identity && this.legacyKeys.has(this.hash(identity))) {
        const key = this.hash(identity);
        this.remember(peer, key);
        return key;
      }
    }
    const identity = peer.conversation_id || link || fallback;
    return identity ? this.hash(identity) : '';
  }
}
