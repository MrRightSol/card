import { Component, Input, OnChanges, SimpleChanges } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient, HttpClientModule } from '@angular/common/http';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';

@Component({
  selector: 'app-clawback',
  standalone: true,
  imports: [CommonModule, FormsModule, HttpClientModule, MatCardModule, MatButtonModule, MatIconModule],
  template: `
  <mat-card>
    <h3>Claw Back Job: {{ jobId || '(none)' }}</h3>
    <div *ngIf="!jobId">No job selected.</div>
    <div *ngIf="job">
      <div>Employees: {{ job.items?.length }} Transactions: {{ transactionsCount }}</div>
      <div style="margin-top:12px">
        <button mat-raised-button color="primary" (click)="prev()" [disabled]="index<=0">&lt;&lt; Prev</button>
        <button mat-raised-button color="primary" (click)="next()" [disabled]="index+1>= (job.items?.length || 0)">Next &gt;&gt;</button>
        <button mat-stroked-button color="accent" (click)="simulateAll()">Notify Employees (simulate)</button>
      </div>
      <div style="margin-top:12px">
        <textarea [(ngModel)]="currentEmail" rows="12" style="width:100%"></textarea>
      </div>
      <div style="margin-top:8px">
        <button mat-raised-button color="primary" (click)="saveCurrent()">Save</button>
      </div>
    </div>
  </mat-card>
  `,
})
export class ClawbackComponent implements OnChanges{
  @Input() jobId: string | null = null;
  job: any = null;
  index = 0;
  currentEmail = '';
  constructor(private http: HttpClient){}
  ngOnChanges(ch: SimpleChanges){
    if(ch['jobId'] && this.jobId) this.loadJob(this.jobId);
  }
  async loadJob(id: string){
    try{
      // Check for cached payload on window (set by the creator to avoid a GET)
      const cache = (window as any).__clawback_cache || {};
      if(cache && cache[id]){ this.job = cache[id]; this.index = 0; this.refreshCurrent(); return; }
      const j = await this.http.get<any>(`/clawback/job/${encodeURIComponent(id)}`).toPromise(); this.job = j; this.index = 0; this.refreshCurrent();
    }catch(e){ console.error(e); alert('Failed to load job '+id); }
  }
  refreshCurrent(){
    const it = (this.job?.items || [])[this.index];
    if(!it){ this.currentEmail=''; return; }
    this.currentEmail = it.rendered_email || '';
  }
  prev(){ if(this.index>0){ this.index--; this.refreshCurrent(); }}
  next(){ if(this.index+1 < (this.job?.items||[]).length){ this.index++; this.refreshCurrent(); }}
  async saveCurrent(){
    const it = (this.job?.items || [])[this.index]; if(!it) return; 
    try{ const body = { rendered_email: this.currentEmail }; const updated = await this.http.patch<any>(`/clawback/job/${encodeURIComponent(this.jobId || '')}/item/${encodeURIComponent(it.item_id)}`, body).toPromise(); this.job.items[this.index] = updated; alert('Saved'); }catch(e){ console.error(e); alert('Save failed'); }
  }
  async simulateAll(){
    if(!this.job) return; try{ const ids = (this.job.items || []).map((i:any)=> i.item_id); const res = await this.http.post<any>(`/clawback/job/${encodeURIComponent(this.job.job_id)}/simulate-send`, { item_ids: ids }).toPromise(); alert('Simulated: '+(res.results?.length||0)); this.loadJob(this.job.job_id); }catch(e){ console.error(e); alert('Simulate failed'); }
  }

  get transactionsCount(): number{
    if(!this.job) return 0;
    if(this.job.transactions_count) return this.job.transactions_count;
    let sum = 0;
    const items = this.job.items || [];
    for(const it of items){
      if(Array.isArray(it.txn_ids)) sum += it.txn_ids.length;
      else if(typeof it.txn_id === 'string' && it.txn_id.trim()) sum += it.txn_id.split(',').filter((x: string) => x.trim()).length;
    }
    return sum;
  }
}
