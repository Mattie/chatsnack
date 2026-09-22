/** One page-local request lane. Revisions prevent old responses replacing newer text. */
export class Evaluator {
  constructor(demos, configured, send, changed, timers = globalThis) {
    this.tabs = Object.fromEntries(demos.map(d => [d.id, {text:d.sample, revision:0, resultRevision:-1, results:[], model:'', error:'', status:'idle'}]));
    this.active = demos[0].id; this.configured = configured;
    this.send = send; this.changed = changed; this.timers = timers;
    this.timer = null; this.pending = null; this.inflight = null;
  }
  select(id) {
    this.active = id;
    this.cancelPending();
    const tab = this.tabs[id];
    if (tab.resultRevision !== tab.revision && !tab.error) this.schedule();
    this.changed();
  }
  edit(text) {
    const tab = this.tabs[this.active];
    tab.text = text; tab.revision++; tab.error = '';
    this.schedule(); this.changed();
  }
  cancelPending() {
    if (this.timer !== null) this.timers.clearTimeout(this.timer);
    this.timer = null;
    if (this.pending) this.tabs[this.pending.id].status = 'idle';
    this.pending = null;
  }
  schedule() {
    this.cancelPending();
    const id = this.active, tab = this.tabs[id];
    if (!this.configured || !tab.text.trim() || tab.text.length > 20000) {tab.status = 'idle'; return;}
    if (this.inflight?.id === id && this.inflight.revision === tab.revision) return;
    tab.status = 'waiting';
    this.pending = {id, text:tab.text, revision:tab.revision, ready:false};
    this.timer = this.timers.setTimeout(() => {
      this.timer = null;
      if (this.pending) this.pending.ready = true;
      this.drain();
    }, 800);
  }
  retry() {this.tabs[this.active].error = ''; this.schedule(); this.changed();}
  async drain() {
    if (this.inflight || !this.pending?.ready) return;
    const job = this.pending; this.pending = null; this.inflight = job;
    const tab = this.tabs[job.id]; tab.status = 'loading'; this.changed();
    try {
      const data = await this.send(job.id, job.text);
      if (tab.revision === job.revision) {
        tab.results = data.results; tab.model = data.model;
        tab.resultRevision = job.revision; tab.error = ''; tab.status = 'idle';
      }
    } catch (error) {
      if (tab.revision === job.revision) {tab.error = error.message; tab.status = 'idle';}
    } finally {
      this.inflight = null; this.changed(); this.drain();
    }
  }
}
