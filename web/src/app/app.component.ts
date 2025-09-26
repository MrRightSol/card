import { Component, signal, computed, ViewChild, AfterViewInit } from '@angular/core';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { SecurityContext } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
// SnackBar not used currently; omit module to reduce risk
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatStepperModule } from '@angular/material/stepper';
import { MatCardModule } from '@angular/material/card';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatTableDataSource, MatTableModule } from '@angular/material/table';
import { MatPaginator, MatPaginatorModule } from '@angular/material/paginator';
import { MatSort, MatSortModule } from '@angular/material/sort';
import { MatListModule } from '@angular/material/list';
import { MatSliderModule } from '@angular/material/slider';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { BrowserAnimationsModule } from '@angular/platform-browser/animations';

interface RuleDoc { rules: any[]; version: string; source: string; }
interface TrainResp { algo: string; fit_seconds: number; features: string[] }
interface ScoreRow { txn_id: string; amount: number; category: string; fraud_score: number; policy: { compliant: boolean; violated_rules: string[]; reason: string } }

@Component({
  selector: 'app-root',
  standalone: true,
  template: `
  <mat-toolbar color="primary">
    <span class="material-icons" style="margin-right:8px">credit_card</span>
    <span>Expense Fraud & Policy Compliance</span>
    <span style="flex:1 1 auto"></span>
    <span>Health:</span>
    <span class="badge" style="margin-left:6px" [class.ok]="health==='ok'" [class.violation]="health!=='ok'">{{ health }}</span>
  </mat-toolbar>

  <mat-progress-bar *ngIf="busy" mode="indeterminate"></mat-progress-bar>

  <div class="container">
    <mat-card style="margin-bottom:16px">
      <div class="row">
        <mat-form-field appearance="outline" style="flex:1">
          <mat-label>API URL</mat-label>
          <input matInput [(ngModel)]="apiUrlInput" placeholder="http://localhost:8080">
        </mat-form-field>
        <button mat-raised-button color="accent" (click)="saveApiUrl()">Save</button>
      </div>
    </mat-card>

    <mat-stepper labelPosition="bottom">
      <mat-step [completed]="!!datasetPath()" label="Generate Data">
        <div class="row">
          <mat-form-field appearance="outline">
            <mat-label>Rows</mat-label>
            <input matInput type="number" [(ngModel)]="rows" min="100" step="1000">
          </mat-form-field>
          <mat-form-field appearance="outline">
            <mat-label>Seed</mat-label>
            <input matInput type="number" [(ngModel)]="seed">
          </mat-form-field>
          <button mat-raised-button color="primary" (click)="generateSynth()" [disabled]="busy">Generate</button>
        </div>
        <!-- table moved below filters so filters appear above the grid -->
        <div *ngIf="datasetPath()">Path: {{ datasetPath() }}</div>
      
        <!-- Browse Transactions and Logs moved into Generate Data step -->
        <mat-card style="margin-top:16px">
          <h3>Browse Transactions (DB)</h3>
          <div class="row">
            <button mat-raised-button color="warn" (click)="truncateTransactions()">Truncate</button>
            <button mat-raised-button color="accent" (click)="loadTransactions()">Load</button>
            <button mat-raised-button color="primary" (click)="loadCsvIntoDb(true)" [disabled]="!datasetPath()">Load Generated CSV (truncate)</button>
            <button mat-stroked-button color="primary" (click)="loadCsvIntoDb(false)" [disabled]="!datasetPath()">Load Generated CSV (append)</button>
            <span style="align-self:center">Total: {{ txTotal }}</span>
            <span style="flex:1 1 auto"></span>
            <div style="display:flex; gap:8px; align-items:center">
              <div style="display:flex; flex-direction:column">
                <label style="font-size:0.75rem;color:rgba(0,0,0,0.6)">Sort by</label>
              <mat-form-field appearance="outline" style="min-width:140px">
                <mat-select [(ngModel)]="txSortBy">
                  <mat-option value="timestamp">Timestamp</mat-option>
                  <mat-option value="amount">Amount</mat-option>
                  <mat-option value="merchant">Merchant</mat-option>
                  <mat-option value="category">Category</mat-option>
                  <mat-option value="city">City</mat-option>
                </mat-select>
              </mat-form-field>
              </div>
              <div style="display:flex; flex-direction:column">
                <label style="font-size:0.75rem;color:rgba(0,0,0,0.6)">Dir</label>
                <mat-form-field appearance="outline" style="min-width:100px">
                  <mat-select [(ngModel)]="txSortDir">
                    <mat-option value="desc">Desc</mat-option>
                    <mat-option value="asc">Asc</mat-option>
                  </mat-select>
                </mat-form-field>
              </div>
            </div>
            <button mat-stroked-button (click)="txPrev()" [disabled]="txPage===0">Prev</button>
            <span style="align-self:center">Page {{ txPage+1 }} / {{ txTotalPages() }}</span>
            <button mat-stroked-button (click)="txNext()" [disabled]="txPage+1>=txTotalPages()">Next</button>
          </div>
          <div class="row">
            <mat-form-field appearance="outline"><mat-label>Employee</mat-label><input matInput [(ngModel)]="txFilter.employee_id"></mat-form-field>
            <div style="display:flex; flex-direction:column; min-width:220px;">
              <label style="font-size:0.75rem;color:rgba(0,0,0,0.6)">Merchant</label>
              <mat-form-field appearance="outline" style="min-width:220px">
                <mat-select [(ngModel)]="txFilter.merchant" (openedChange)="fetchDistinct('merchant')">
                  <mat-option value="">(any)</mat-option>
                  <mat-option *ngFor="let m of merchants" [value]="m">{{ m }}</mat-option>
                </mat-select>
              </mat-form-field>
            </div>
            <div style="display:flex; flex-direction:column; min-width:160px;">
              <label style="font-size:0.75rem;color:rgba(0,0,0,0.6)">City</label>
              <mat-form-field appearance="outline" style="min-width:160px">
                <mat-select [(ngModel)]="txFilter.city" (openedChange)="fetchDistinct('city')">
                  <mat-option value="">(any)</mat-option>
                  <mat-option *ngFor="let c of cities" [value]="c">{{ c }}</mat-option>
                </mat-select>
              </mat-form-field>
            </div>
            <div style="display:flex; flex-direction:column; min-width:160px;">
              <label style="font-size:0.75rem;color:rgba(0,0,0,0.6)">Category</label>
              <mat-form-field appearance="outline" style="min-width:160px">
                <mat-select [(ngModel)]="txFilter.category" (openedChange)="fetchDistinct('category')">
                  <mat-option value="">(any)</mat-option>
                  <mat-option *ngFor="let c of categories" [value]="c">{{ c }}</mat-option>
                </mat-select>
              </mat-form-field>
            </div>
            <mat-form-field appearance="outline"><mat-label>Min Amount</mat-label><input matInput type="number" [(ngModel)]="txFilter.min_amount"></mat-form-field>
            <mat-form-field appearance="outline"><mat-label>Max Amount</mat-label><input matInput type="number" [(ngModel)]="txFilter.max_amount"></mat-form-field>
            <div style="display:flex; align-items:center; gap:8px; margin-left:auto">
              <button mat-stroked-button (click)="applyFilters()">Apply Filters</button>
              <button mat-stroked-button (click)="clearFilters()">Clear</button>
            </div>
          </div>
          <!-- Data grid placed here, showing rows that reflect active filters -->
          <div style="margin-top:12px; overflow:auto;">
            <table style="width:100%; border-collapse:collapse; font-size:0.95rem;">
              <thead>
                <tr style="text-align:left; border-bottom:1px solid #ddd;">
                  <th style="padding:8px; cursor:pointer" (click)="headerSort('txn_id')">Txn ID {{ sortIconHeader('txn_id') }}</th>
                  <th style="padding:8px; cursor:pointer" (click)="headerSort('employee_id')">Employee {{ sortIconHeader('employee_id') }}</th>
                  <th style="padding:8px; cursor:pointer" (click)="headerSort('merchant')">Merchant {{ sortIconHeader('merchant') }}</th>
                  <th style="padding:8px; cursor:pointer" (click)="headerSort('city')">City {{ sortIconHeader('city') }}</th>
                  <th style="padding:8px; cursor:pointer" (click)="headerSort('category')">Category {{ sortIconHeader('category') }}</th>
                  <th style="padding:8px; cursor:pointer" (click)="headerSort('amount')">Amount {{ sortIconHeader('amount') }}</th>
                  <th style="padding:8px; cursor:pointer" (click)="headerSort('timestamp')">Timestamp {{ sortIconHeader('timestamp') }}</th>
                  <th style="padding:8px; cursor:pointer" (click)="headerSort('channel')">Channel {{ sortIconHeader('channel') }}</th>
                  <th style="padding:8px;">Card</th>
                </tr>
              </thead>
              <tbody>
                <tr *ngFor="let r of txRows" style="border-bottom:1px solid #f2f2f2;">
                  <td style="padding:8px">{{ r.txn_id }}</td>
                  <td style="padding:8px">{{ r.employee_id }}</td>
                  <td style="padding:8px">{{ r.merchant }}</td>
                  <td style="padding:8px">{{ r.city }}</td>
                  <td style="padding:8px">{{ r.category }}</td>
                  <td style="padding:8px">{{ r.amount }}</td>
                  <td style="padding:8px">{{ r.timestamp }}</td>
                  <td style="padding:8px">{{ r.channel }}</td>
                  <td style="padding:8px">{{ r.card_id }}</td>
                </tr>
                <tr *ngIf="txRows.length===0">
                  <td colspan="9" style="padding:12px; text-align:center; color:#666">No transactions loaded.</td>
                </tr>
              </tbody>
            </table>
          </div>
        </mat-card>

          <mat-card style="margin-top:16px">
            <h3>Logs <button mat-stroked-button (click)="toggleLogs()" style="margin-left:12px">{{ logsVisible ? 'Hide' : 'Show' }}</button></h3>
            <div class="row">
              <button mat-raised-button color="accent" (click)="loadLogs()">Refresh</button>
            </div>
            <div *ngIf="logsVisible">
              <mat-list>
                <mat-list-item *ngFor="let l of combinedLogsFiltered()" style="display:flex; flex-direction:column; align-items:flex-start;">
                  <div style="width:100%; display:flex; align-items:center; gap:12px;">
                    <div style="flex:1">{{ l.ts }} — <strong>{{ l.type }}</strong></div>
                    <button mat-button (click)="toggleLogDetail(l)">{{ isLogExpanded(l) ? 'Hide' : 'Details' }}</button>
                  </div>
                  <div *ngIf="isLogExpanded(l)" style="width:100%; margin-top:8px; font-family:monospace; white-space:pre-wrap; background:#fafafa; padding:8px; border-radius:4px; border:1px solid #eee">{{ formatLogPayload(l) }}</div>
                </mat-list-item>
              </mat-list>
            </div>
          </mat-card>

      </mat-step>

      <mat-step [completed]="!!rulesDoc()" label="Parse Policy">
        <mat-form-field appearance="outline" style="width:100%">
          <mat-label>Policy text</mat-label>
          <textarea matInput rows="4" [(ngModel)]="policyText" placeholder="Paste policy text..."></textarea>
        </mat-form-field>
        <div class="row" style="align-items:center; gap:8px">
        <!-- Hidden native file input; trigger via button to avoid browser showing its own filename text -->
          <!-- keep the input in the DOM (not display:none) so programmatic click is permitted by browsers -->
          <input #fileInput type="file" style="position:absolute; left:-9999px; width:1px; height:1px; overflow:hidden;" (change)="onFile($event)">
          <button mat-stroked-button (click)="chooseFileClicked(fileInput)">Choose file</button>
          <span *ngIf="uploadedFileName" class="selected-file">{{ uploadedFileName }}</span>
          <mat-spinner *ngIf="busy" diameter="20" style="margin-left:8px"></mat-spinner>
          <button mat-raised-button color="primary" (click)="parsePolicyText()" [disabled]="busy">Parse Text</button>
          <mat-checkbox [(ngModel)]="useOpenAI">Use OpenAI</mat-checkbox>
          <div style="display:flex; flex-direction:column;">
            <label style="font-size:0.75rem; color:rgba(0,0,0,0.6)">Model</label>
            <mat-form-field appearance="outline" style="min-width:220px">
              <mat-select [(ngModel)]="selectedModel">
                <mat-option *ngFor="let m of availableModels" [value]="m">{{ m }}</mat-option>
                <mat-option *ngIf="availableModels.length===0" value="gpt-5-mini">gpt-5-mini</mat-option>
              </mat-select>
            </mat-form-field>
          </div>
          <div style="display:flex; flex-direction:column;">
            <label style="font-size:0.75rem; color:rgba(0,0,0,0.6)">Embedding Model</label>
            <mat-form-field appearance="outline" style="min-width:220px">
              <mat-select [(ngModel)]="selectedEmbedModel">
                <mat-option *ngFor="let m of availableEmbedModels" [value]="m">{{ m }}</mat-option>
                <mat-option *ngIf="availableEmbedModels.length===0" value="text-embedding-3-small">text-embedding-3-small</mat-option>
              </mat-select>
            </mat-form-field>
          </div>
          <div *ngIf="useOpenAI" style="display:flex; align-items:center; gap:8px;">
            <mat-slider min="1000" max="50000" step="1000" [value]="selectedMaxTokens" (input)="onSliderChange($event.value)" style="width:320px"></mat-slider>
            <mat-form-field appearance="outline" style="width:120px; margin-left:8px">
              <input matInput type="number" [min]="1000" [max]="50000" step="1000" [(ngModel)]="selectedMaxTokens" (ngModelChange)="onNumberChange($event)">
            </mat-form-field>
          </div>
          <div *ngIf="useOpenAI" style="display:flex; align-items:center; gap:8px; margin-left:8px">
            <mat-checkbox [(ngModel)]="simulateOpenAI">Simulate OpenAI (use saved response)</mat-checkbox>
          </div>
          <button mat-stroked-button (click)="compareParsers()">Compare Parsers</button>
          <div *ngIf="rulesDoc()">Source: {{ rulesDoc()?.source }} (parser={{ rulesDoc()?.parser || rulesDoc()?.source }}), Rules: {{ rulesDoc()?.rules?.length }}</div>
        </div>
        <!-- Uploaded file preview removed (redundant) -->
        <div *ngIf="rulesDoc()" style="margin-top:8px">
          <mat-card>
            <div style="display:flex; align-items:center; gap:8px">
              <h4 style="margin:0">Parsed Policy (JSON)</h4>
              <button mat-stroked-button (click)="showParsedJson = !showParsedJson">{{ showParsedJson ? 'Hide' : 'Show' }}</button>
              <span style="flex:1 1 auto"></span>
              <small>parser: {{ rulesDoc()?.parser || rulesDoc()?.source }}</small>
            </div>
            <div *ngIf="showParsedJson" style="margin-top:8px">
              <textarea rows="12" style="width:100%" [(ngModel)]="parsedJsonText"></textarea>
              <div style="display:flex; gap:8px; margin-top:8px">
                <button mat-raised-button color="primary" (click)="applyParsedJson()">Apply Parsed JSON</button>
                <div *ngIf="parsedJsonError" style="color:darkred">{{ parsedJsonError }}</div>
                <div *ngIf="rulesDoc()?.extracted" style="margin-left:auto; color:darkorange">Note: JSON extracted from model output</div>
              </div>
            </div>
          </mat-card>
        </div>
        <!-- Bots and Policy Chat inserted here for Parse Policy step -->

        <mat-card style="margin-top:16px">
          <h3>Bots</h3>
      <div class="row">
        <button mat-raised-button color="primary" (click)="createBot()" [disabled]="!rulesDoc()">Create Bot from Parsed Policy</button>
        <button mat-stroked-button (click)="loadBots()">Refresh</button>
      </div>
      <mat-list>
        <mat-list-item *ngFor="let b of bots">{{ b.id }} — {{ b.name }} — <button mat-raised-button color="primary" (click)="openChat(b)">Chat</button> <button mat-raised-button color="warn" (click)="deleteBot(b.id)">Delete</button> <div style="margin-left:8px; font-size:0.85rem;color:#666">model: {{ b.model }}{{ b.embed_model ? ' / embed:' + b.embed_model : '' }}</div></mat-list-item>
      </mat-list>
    </mat-card>
          <mat-card *ngIf="activeBot" style="margin-top:16px">
          <h3>Chat — {{ activeBot?.name }} <button mat-button style="float:right" (click)="activeBot=null; chatMessages=[]">Close Chat</button></h3>
          <div style="display:flex; gap:12px; align-items:center; margin-top:8px">
            <div style="display:flex; flex-direction:column">
              <label style="font-size:0.75rem; color:rgba(0,0,0,0.6)">Model (bot default: {{ activeBot?.model }})</label>
              <mat-form-field appearance="outline" style="min-width:220px">
                <mat-select [(ngModel)]="botChatModelOverride">
                  <mat-option [value]="activeBot?.model">(bot default) {{ activeBot?.model }}</mat-option>
                  <mat-option *ngFor="let m of availableModels" [value]="m">{{ m }}</mat-option>
                </mat-select>
              </mat-form-field>
            </div>
            <div style="display:flex; flex-direction:column">
              <label style="font-size:0.75rem; color:rgba(0,0,0,0.6)">Embedding Model (bot default: {{ activeBot?.embed_model }})</label>
              <mat-form-field appearance="outline" style="min-width:220px">
                <mat-select [(ngModel)]="botChatEmbedOverride">
                  <mat-option [value]="activeBot?.embed_model">(bot default) {{ activeBot?.embed_model }}</mat-option>
                  <mat-option *ngFor="let m of availableEmbedModels" [value]="m">{{ m }}</mat-option>
                </mat-select>
              </mat-form-field>
            </div>
          </div>
          <div style="max-height:240px; overflow:auto; border:1px solid #eee; padding:8px">
            <div *ngFor="let m of chatMessages">
              <div *ngIf="m.role==='user'" style="text-align:right"><b>You:</b> {{ m.text }}</div>
              <div *ngIf="m.role==='bot'" style="text-align:left">
                <div *ngIf="m.thinking" style="display:flex; align-items:center; gap:8px">
                  <mat-spinner diameter="18"></mat-spinner>
                  <div style="font-style:italic;color:#666">Thinking...</div>
                </div>
                <div *ngIf="!m.thinking">
                  <b>Bot:</b> {{ m.text }} <small *ngIf="m.sources">(sources: {{ m.sources.length }})</small>
                </div>
              </div>
            </div>
          </div>
          <div style="display:flex; gap:8px; margin-top:8px; align-items:center">
            <mat-form-field appearance="outline" style="flex:1; margin:0">
              <input matInput #chatbox>
            </mat-form-field>
            <button mat-raised-button color="primary" (click)="sendBotMessage(chatbox.value); chatbox.value=''">Send</button>
          </div>
        </mat-card>
<mat-card style="margin-top:16px">
      <h3>Policy Chat (RAG)</h3>
      <div style="max-height:240px; overflow:auto; border:1px solid #eee; padding:8px">
        <div *ngFor="let m of chatPolicyMessages">
          <div *ngIf="m.role==='user'" style="text-align:right"><b>You:</b> {{ m.text }}</div>
          <div *ngIf="m.role==='bot'" style="text-align:left">
            <div *ngIf="m.thinking" style="display:flex; align-items:center; gap:8px">
              <mat-spinner diameter="20"></mat-spinner>
              <div style="font-style:italic;color:#666">Thinking...</div>
            </div>
            <div *ngIf="!m.thinking">
              <div *ngIf="m.structured">
                <div><strong>Answer:</strong></div>
                <div style="margin-left:8px">{{ m.structured.answer }}</div>
                <div style="margin-top:8px"><strong>Reasoning:</strong></div>
                <ul><li *ngFor="let r of m.structured.reasoning">{{ r }}</li></ul>
                <div style="margin-top:8px"><strong>Policy Reference:</strong></div>
                <ul><li *ngFor="let rf of m.structured.references">{{ rf }}</li></ul>
              </div>
              <div *ngIf="!m.structured">
                <div *ngIf="m.formatted_html" [innerHTML]="m.formatted_html"></div>
                <div *ngIf="!m.formatted_html"><b>Bot:</b> {{ m.text }} <small *ngIf="m.sources">(sources: {{ m.sources_readable?.join(',') || m.sources?.length }})</small></div>
                <div *ngIf="m.sources_readable && m.sources_readable.length" style="font-size:0.8rem;color:#666">Sources: <span *ngFor="let s of m.sources_readable; let i = index">{{ s }}<span *ngIf="i+1 < m.sources_readable.length">, </span></span></div>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div style="display:flex; gap:8px; margin-top:8px; align-items:center">
        <mat-form-field appearance="outline" style="flex:1; margin:0">
          <input matInput #policybox>
        </mat-form-field>
        <mat-form-field appearance="outline" style="width:220px; margin-left:8px">
          <mat-label>Model</mat-label>
          <mat-select [(ngModel)]="selectedModel">
            <mat-option *ngFor="let m of availableModels" [value]="m">{{ m }}</mat-option>
            <mat-option *ngIf="availableModels.length===0" value="gpt-5-mini">gpt-5-mini</mat-option>
          </mat-select>
        </mat-form-field>
        <mat-form-field appearance="outline" style="width:220px; margin-left:8px">
          <mat-label>Embedding Model</mat-label>
          <mat-select [(ngModel)]="selectedEmbedModel">
            <mat-option *ngFor="let m of availableEmbedModels" [value]="m">{{ m }}</mat-option>
            <mat-option *ngIf="availableEmbedModels.length===0" value="text-embedding-3-small">text-embedding-3-small</mat-option>
          </mat-select>
        </mat-form-field>
        <button mat-raised-button color="primary" (click)="sendPolicyQuery(policybox.value); policybox.value=''">Ask Policy</button>
        <button *ngIf="indexMissing" mat-stroked-button color="accent" (click)="buildIndex()">Build Index</button>
      </div>
    </mat-card>

        

        

        <div *ngIf="compareResult" style="margin-top:8px; display:flex; gap:8px">
          <mat-card style="flex:1">
            <h4>Heuristic</h4>
            <pre>{{ compareResult.heuristic | json }}</pre>
          </mat-card>
          <mat-card style="flex:1">
            <h4>OpenAI ({{ selectedModel }})</h4>
            <pre>{{ compareResult.openai | json }}</pre>
          </mat-card>
        </div>
      </mat-step>

      <mat-step [completed]="!!trained()" label="Train">
        <div class="row">
      <div style="display:flex; align-items:center; gap:8px">
          <mat-form-field appearance="outline">
            <mat-label>Algo</mat-label>
            <mat-select [(ngModel)]="algo">
              <mat-option *ngFor="let a of (availableAlgosObjs.length ? availableAlgosObjs : [{id:'isolation_forest',label:'Isolation Forest'}])" [value]="a.id">{{ a.label }}</mat-option>
            </mat-select>
          </mat-form-field>
          <div style="margin-left:8px; display:flex; flex-direction:column; gap:8px">
            <div style="font-size:0.8rem;color:#666">Available: {{ availableAlgos.length }} </div>
          </div>
          <div style="display:flex; align-items:center; gap:8px; margin-left:12px">
            <span style="font-size:0.85rem;color:#666">Source:</span>
            <div style="display:flex; align-items:center; gap:8px">
              <span class="badge source-badge" title="Click to change source (Auto → CSV → DB)" style="cursor:pointer"
                    [class.auto]="selectedDataSource==='auto'" [class.csv]="selectedDataSource==='csv'" [class.db]="selectedDataSource==='db'"
                    (click)="toggleDataSource()">{{ selectedDataSource==='auto' ? 'Auto' : (selectedDataSource==='csv' ? 'CSV' : 'DB') }}</span>
              <div style="align-self:center; margin-left:4px">{{ datasetPath() ? ('CSV: '+ datasetPath()) : (txTotal ? ('DB rows: '+ txTotal) : 'None') }}</div>
            </div>
          </div>
          <div *ngIf="availableAlgos.length===0">
            <mat-form-field appearance="outline">
              <mat-label>Algo</mat-label>
              <mat-select [(ngModel)]="algo">
                <mat-option [value]="'isolation_forest'">{{ algoLabels['isolation_forest'] || 'isolation_forest' }}</mat-option>
              </mat-select>
            </mat-form-field>
          </div>
      </div>
            <mat-form-field appearance="outline">
            <mat-label>Max rows</mat-label>
            <input matInput type="number" [(ngModel)]="maxRows" (ngModelChange)="userChangedMaxRows=true" min="1">
          </mat-form-field>
          <mat-checkbox [(ngModel)]="includePolicyFeatures">Include policy features</mat-checkbox>
          <button mat-raised-button color="primary" (click)="train()" [disabled]="busy">Train</button>
        <div *ngIf="trainingJobId" style="align-self:center; margin-left:8px">Training job: {{ trainingJobId }} — progress: {{ trainingProgress }}%</div>
        <div *ngIf="trained()" style="align-self:center; margin-left:8px">Trained: {{ trained()?.algo }} in {{ trained()?.fit_seconds | number:'1.1-2' }}s</div>
        </div>
      </mat-step>

      <mat-step label="Score">
        <div class="row" style="align-items:center; gap:12px">
          <button mat-raised-button color="primary" (click)="score()" [disabled]="busy || scoringBusy || (!datasetPath() && !txTotal)">
            <span *ngIf="!scoringBusy">Score</span>
            <span *ngIf="scoringBusy">Scoring...</span>
          </button>
          <mat-spinner *ngIf="scoringBusy" diameter="20"></mat-spinner>
          <div *ngIf="scores().length">Rows: {{ scores().length }}</div>
          <div style="flex:1 1 auto"></div>
          <div style="display:flex; gap:8px; align-items:center">
            <mat-form-field appearance="outline" style="min-width:180px">
              <mat-label>Category</mat-label>
              <mat-select [(ngModel)]="filterCategory" (selectionChange)="applyScoreFilters()">
                <mat-option value="">(All)</mat-option>
                <mat-option *ngFor="let c of scoreCategories" [value]="c">{{ c }}</mat-option>
              </mat-select>
            </mat-form-field>
            <mat-form-field appearance="outline" style="min-width:160px">
              <mat-label>Fraud</mat-label>
              <mat-select [(ngModel)]="filterFraud" (selectionChange)="applyScoreFilters()">
                <mat-option value="">(All)</mat-option>
                <mat-option value="high">High</mat-option>
                <mat-option value="med">Med</mat-option>
                <mat-option value="low">Low</mat-option>
              </mat-select>
            </mat-form-field>
            <mat-form-field appearance="outline" style="min-width:160px">
              <mat-label>Policy</mat-label>
              <mat-select [(ngModel)]="filterPolicy" (selectionChange)="applyScoreFilters()">
                <mat-option value="">(All)</mat-option>
                <mat-option value="violation">Violation</mat-option>
                <mat-option value="ok">OK</mat-option>
              </mat-select>
            </mat-form-field>
            <button mat-stroked-button (click)="clearScoreFilters()">Clear</button>
            <button mat-raised-button color="warn" (click)="startClawBack()" [disabled]="scores().length===0">Start Claw Back</button>
            <div style="align-self:center;margin-left:8px">
              <span style="font-size:0.9rem;color:#333">Selected: {{ selectedTxnIds.size }}</span>
            </div>
            <div style="align-self:center;margin-left:8px">
              <button mat-button (click)="toggleSelectAll(true)">Select all results</button>
            </div>
          </div>
        </div>

        <div *ngIf="scores().length" style="margin-top:8px">
          <table mat-table [dataSource]="dataSource" matSort class="mat-elevation-z2">
            <ng-container matColumnDef="select">
              <th mat-header-cell *matHeaderCellDef>
                <mat-checkbox [checked]="areAllVisibleSelected()" (change)="toggleSelectAll($event.checked)"></mat-checkbox>
              </th>
              <td mat-cell *matCellDef="let r">
                <mat-checkbox [checked]="isSelected(r.txn_id)" (change)="toggleSelect(r.txn_id, $event.checked)"></mat-checkbox>
              </td>
            </ng-container>
            <ng-container matColumnDef="txn_id">
              <th mat-header-cell *matHeaderCellDef mat-sort-header>Txn</th>
              <td mat-cell *matCellDef="let r">{{ r.txn_id }}</td>
            </ng-container>
            <ng-container matColumnDef="category">
              <th mat-header-cell *matHeaderCellDef mat-sort-header>Category</th>
              <td mat-cell *matCellDef="let r">{{ r.category }}</td>
            </ng-container>
            <ng-container matColumnDef="amount">
              <th mat-header-cell *matHeaderCellDef mat-sort-header>Amount</th>
              <td mat-cell *matCellDef="let r">{{ r.amount | number:'1.2-2' }}</td>
            </ng-container>
            <ng-container matColumnDef="fraud_score">
              <th mat-header-cell *matHeaderCellDef mat-sort-header>Fraud</th>
              <td mat-cell *matCellDef="let r">
                <span [title]="r.fraud_score | number:'1.2-2'"
                      [ngClass]="{ 'badge-high': r.fraud_score>0.5, 'badge-med': r.fraud_score>0.2 && r.fraud_score<=0.5, 'badge-low': r.fraud_score<=0.2 }"
                      style="padding:6px 8px; border-radius:6px; color:white; display:inline-block">
                  {{ r.fraud_score>0.5 ? 'High' : (r.fraud_score>0.2 ? 'Med' : 'Low') }}
                </span>
              </td>
            </ng-container>
            <ng-container matColumnDef="policy">
              <th mat-header-cell *matHeaderCellDef>Policy</th>
              <td mat-cell *matCellDef="let r">
                <span class="badge" [class.ok]="r.policy?.compliant" [class.violation]="!r.policy?.compliant">
                  {{ r.policy?.compliant ? 'OK' : 'Violation' }}
                </span>
              </td>
            </ng-container>

            <tr mat-header-row *matHeaderRowDef="displayedColumns"></tr>
            <tr mat-row *matRowDef="let row; columns: displayedColumns;"></tr>
          </table>
          <mat-paginator [pageSize]="50" [pageSizeOptions]="[25,50,100]"></mat-paginator>
        </div>
      </mat-step>
    </mat-stepper>

      

    
  </div>
  `,
  styles: [
    `
    .selected-file{ display:inline-block; padding:4px 8px; background:#f1f3f4; border-radius:6px; font-size:0.9rem; color:rgba(0,0,0,0.87); margin-left:6px;}
    .badge-high{ background:#d32f2f }
    .badge-med{ background:#f57c00 }
    .badge-low{ background:#2e7d32 }
    .badge{ padding:6px 8px; border-radius:6px; color:white; display:inline-block }
    .badge.ok{ background:#2e7d32 }
    .badge.violation{ background:#d32f2f }
    .source-badge{ min-width:72px; text-align:center }
    .source-badge.auto{ background:#1976d2 }
    .source-badge.csv{ background:#6a1b9a }
    .source-badge.db{ background:#00796b }
    `
  ],
  imports: [
    CommonModule, FormsModule, BrowserAnimationsModule,
    MatToolbarModule, MatButtonModule, MatIconModule,
    MatFormFieldModule, MatInputModule, MatSelectModule,
    MatSliderModule,
    MatProgressBarModule,
    MatStepperModule, MatCardModule,
    MatCheckboxModule,
    MatTableModule, MatPaginatorModule, MatSortModule,
    MatListModule
    , MatProgressSpinnerModule
  ]
})
export class AppComponent implements AfterViewInit {
  constructor(private sanitizer: DomSanitizer){}
  apiUrl = (localStorage.getItem('VITE_API_URL') || 'http://localhost:8080').replace(/\/$/, '');
  apiUrlInput = this.apiUrl;
  health: 'ok' | 'down' | 'unknown' = 'unknown';
  rows = 5000;
  seed = 42;
  policyText = 'Meals reimbursable up to $200/day; hotel up to $300/night.';
  // uploaded file preview
  uploadedFileContent: string | null = null;
  uploadedFileName: string | null = null;
  showParsedJson = false;
  // parser selection: default heuristic, optional OpenAI
  useOpenAI = false;
  // adjustable max tokens for OpenAI (persisted in localStorage)
  selectedMaxTokens = (() => {
    try{ const v = Number(localStorage.getItem('OPENAI_MAX_COMPLETION_TOKENS')||''); return v && !isNaN(v) ? v : 10000; }catch{ return 10000; }
  })();
  // simulate OpenAI by returning latest saved response from server
  simulateOpenAI = false;
  // editable parsed JSON and validation
  parsedJsonText: string = '';
  parsedJsonError: string | null = null;
  algo = 'isolation_forest';
  maxRows = 20000;
  userChangedMaxRows = false;
  availableAlgos: string[] = [];
  availableAlgosObjs: { id: string; label: string }[] = [];
  trainingJobId: string | null = null;
  trainingProgress = 0;
  pageSize = 50;
  pageIndex = 0;
  sortField: keyof ScoreRow | '' = '';
  sortDir: 'asc' | 'desc' = 'asc';
  busy = false;
  scoringBusy = false;

  datasetPath = signal<string | null>(null);
  rulesDoc = signal<RuleDoc | null>(null);
  trained = signal<TrainResp | null>(null);
  scores = signal<ScoreRow[]>([]);
    // logs fetched from backend
    logs: any[] = [];
    // client-side logs for tracing UI actions (clicks, file reads, uploads)
    clientLogs: any[] = [];

    combinedLogs(){ return [...this.clientLogs, ...this.logs]; }

  combinedLogsFiltered(){
    return this.combinedLogs().filter(l => l.type !== 'client:file_selected');
  }

  async startClawBack(){
    try{
      const selected = Array.from(this.selectedTxnIds.size ? this.selectedTxnIds : this.scores().map(s=>s.txn_id));
      if(!selected || selected.length===0){ alert('No transactions selected for Claw Back'); return; }
      // Validate selection on server
      const vresp = await fetch(`${this.apiUrl}/clawback/validate-selection`, {
        method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ selected_txn_ids: selected })
      });
      if(!vresp.ok){ const txt = await vresp.text(); alert('Validation failed: '+vresp.status+' '+txt); return; }
      const vjson = await vresp.json();
      if(vjson.missing_txn_ids && vjson.missing_txn_ids.length){
        const ok = confirm('Some transactions are missing from the DB (count='+vjson.missing_txn_ids.length+'). Proceed and ignore missing?');
        if(!ok) return;
      }
      // create job via convenience endpoint
      const body = { name: 'Claw Back from Scores', created_by: 'web-ui', selected_txn_ids: selected, template_text: null, allow_missing: true };
      const jresp = await fetch(`${this.apiUrl}/clawback/initiate-from-selection`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body) });
      const jjson = await jresp.json();
      if(!jresp.ok){ alert('Failed to create job: '+(jjson.detail || JSON.stringify(jjson))); return; }
      if(jjson.status && jjson.status==='validation_failed'){
        alert('Validation failed: missing txns: '+(jjson.missing_txn_ids||[]).join(',')); return;
      }
      if(jjson.status && jjson.status==='created'){
        const jobId = jjson.job_id;
        // redirect to Claw Back UI
        window.location.href = '/clawback/ui?job=' + encodeURIComponent(jobId);
      } else {
        alert('Unexpected response: '+JSON.stringify(jjson));
      }
    }catch(e:any){
      console.error('startClawBack error', e);
      alert('Failed to start Claw Back: '+String(e));
    }
  }

  formatLogPayload(l: any){
    try{
      const p = l.payload;
      if(!p) return '';
      if(String(l.type).endsWith('openai_response_received')){
        const s = JSON.stringify(p);
        return s.length>1000 ? s.slice(0,1000)+' ...' : s;
      }
      if(p.rows) return String(p.rows);
      if(p.name) return String(p.name);
      if(p.error) return String(p.error);
      return JSON.stringify(p).slice(0,300);
    }catch(e){ return '' }
  }
  displayedColumns: string[] = ['select','txn_id','category','amount','fraud_score','policy'];
  dataSource = new MatTableDataSource<ScoreRow>([]);
  // selection state for Claw Back (per-row)
  selectedTxnIds: Set<string> = new Set<string>();

  isSelected(txnId: string){ return this.selectedTxnIds.has(txnId); }
  toggleSelect(txnId: string, checked?: boolean){ if(checked===undefined) checked = !this.selectedTxnIds.has(txnId); if(checked) this.selectedTxnIds.add(txnId); else this.selectedTxnIds.delete(txnId); }
  areAllVisibleSelected(){ const visible = this.pagedScores(); if(!visible || visible.length===0) return false; return visible.every((r:any)=> this.selectedTxnIds.has(r.txn_id)); }
  toggleSelectAll(checked: boolean){ const visible = this.pagedScores(); for(const r of visible){ if(checked) this.selectedTxnIds.add(r.txn_id); else this.selectedTxnIds.delete(r.txn_id); } }
  // keep original unfiltered scores so filters can be applied client-side
  originalScores: ScoreRow[] = [];
  // filters for results
  filterCategory: string = '';
  filterFraud: string = '';
  filterPolicy: string = '';
  scoreCategories: string[] = [];

  // bots
  bots: any[] = [];
  chatMessages: any[] = [];
  activeBot: any = null;
  chatPolicyMessages: any[] = [];
  indexMissing: boolean = false;
  pendingPolicyQuery: string | null = null;


  @ViewChild(MatPaginator) paginator!: MatPaginator;
  @ViewChild(MatSort) sort!: MatSort;

  pagedScores = computed(() => {
    const items = [...this.scores()];
    if (this.sortField) {
      items.sort((a: any, b: any) => {
        const va = a[this.sortField as string];
        const vb = b[this.sortField as string];
        if (va == null && vb == null) return 0;
        if (va == null) return this.sortDir === 'asc' ? -1 : 1;
        if (vb == null) return this.sortDir === 'asc' ? 1 : -1;
        if (typeof va === 'number' && typeof vb === 'number') {
          return this.sortDir === 'asc' ? va - vb : vb - va;
        }
        const sa = String(va).localeCompare(String(vb));
        return this.sortDir === 'asc' ? sa : -sa;
      });
    }
    const start = this.pageIndex * this.pageSize;
    return items.slice(start, start + this.pageSize);
  });

  async generateSynth(){
    this.busy = true;
    try{
      const r = await fetch(`${this.apiUrl}/generate-synth`, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({rows:this.rows, seed:this.seed})
      });
      const j = await r.json();
      this.datasetPath.set(j.path);
      this.pageIndex = 0;
    } finally { this.busy = false; }
  }

  async parsePolicyText(){
    this.busy = true;
    try{
      const parser = this.useOpenAI ? 'openai' : 'heuristic';
      const modelPart = this.useOpenAI ? `&model=${encodeURIComponent(this.selectedModel)}&max_completion_tokens=${encodeURIComponent(String(this.selectedMaxTokens))}` : '';
      this.pushLog('parse_text_start', { parser, model: this.useOpenAI ? this.selectedModel : null });
      try{
        const body = { text: this.policyText };
        if(this.useOpenAI){
          this.pushLog('openai_request_sent', { model: this.selectedModel, body_preview: String(this.policyText).slice(0,2000), length: String(this.policyText).length, max_completion_tokens: this.selectedMaxTokens });
        } else {
          this.pushLog('parse_request_sent', { parser, length: String(this.policyText).length });
        }
        // If simulateOpenAI is enabled, request simulated response from server
        let r;
        if(this.useOpenAI && this.simulateOpenAI){
          r = await fetch(`${this.apiUrl}/debug/openai-simulate?model=${encodeURIComponent(this.selectedModel)}`);
        } else {
          r = await fetch(`${this.apiUrl}/parse-policy?parser=${encodeURIComponent(parser)}${modelPart}`, {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify(body)
          });
        }
        let j = await r.json();
        // If we have a dataset CSV path, try to align parsed categories with available dataset categories
        try{
          const ds = this.datasetPath();
          if(ds && j && j.rules && Array.isArray(j.rules)){
            const cats = await fetch(`${this.apiUrl}/train/dataset/distinct?path=${encodeURIComponent(ds)}&field=category&limit=500`).then(r=>r.json());
            j = this.alignParsedCategoriesWithDataset(j, cats || []);
          }
        }catch(e){ /* non-fatal */ }
        this.pushLog('parse_text_success', { rules: j?.rules?.length ?? null, source: j?.source });
        // Always surface the raw backend response when using OpenAI so users can
        // inspect exactly what the model returned (helps troubleshoot large/malformed outputs)
        if(this.useOpenAI){
          this.parsedJsonText = JSON.stringify(j, null, 2);
          this.pushLog('openai_response_received', { model: this.selectedModel, response_preview: String(this.parsedJsonText).slice(0,2000) });
          // still try to normalize and set rulesDoc if possible
          const norm = this.normalizeParserResponse(j);
          if(!norm.error){ this.rulesDoc.set(norm.doc as any); this.parsedJsonError = null; }
          else { this.parsedJsonError = norm.error; }
        } else {
          const norm = this.normalizeParserResponse(j);
          if(norm.error){ this.parsedJsonError = norm.error; this.parsedJsonText = JSON.stringify(j, null, 2); }
          else { this.rulesDoc.set(norm.doc as any); this.parsedJsonText = JSON.stringify(norm.doc, null, 2); this.parsedJsonError = null; }
        }
      }catch(err:any){
        console.error('parse text failed', err);
        this.pushLog('parse_text_error', { error: String(err && err.message ? err.message : err) });
        this.parsedJsonError = String(err && err.message ? err.message : err);
      }
    } finally { this.busy = false; }
  }

  async onFile(ev: Event){
    const input = ev.target as HTMLInputElement;
    const file = input.files?.[0];
    if(!file){ this.uploadedFileName = null; this.pushLog('file_selection_canceled', {}); return; }
    this.pushLog('file_selected', { name: file.name, size: file.size, type: file.type });
    if(this.uploadedFileName !== file.name) this.uploadedFileName = file.name;
    // Try multiple file-read strategies for maximum compatibility
    this.uploadedFileContent = null;
    let text: string | null = null;
    // preferred modern API
    try{
      if((file as any).text && typeof (file as any).text === 'function'){
        text = await (file as any).text();
      }
    }catch{}
    // fallback to FileReader if blob.text() isn't available, failed, or returned empty
    if(!text){
      try{
        text = await new Promise<string>((resolve, reject) => {
          const fr = new FileReader();
          fr.onerror = () => reject(new Error('File read error'));
          fr.onload = () => resolve(String(fr.result ?? ''));
          fr.readAsText(file);
        });
      }catch(err:any){
        console.warn('onFile read failed', err && err.message);
        text = null;
      }
    }
    if(text != null){
      this.pushLog('file_read_success', { name: file.name, len: text.length });
      this.uploadedFileContent = text;
      this.uploadedFileName = file.name;
      // also populate the main policy text so users see the content immediately
      this.policyText = text;
      this.parsedJsonText = '';
      console.log('onFile: read', file.name, 'len=', (this.uploadedFileContent||'').length);
    } else {
      this.pushLog('file_read_failed', { name: file.name });
    }
    const fd = new FormData();
    fd.append('policy', file, file.name);
    // already populated policyText above; ensure visible
    if(this.uploadedFileContent) this.policyText = this.uploadedFileContent;
    const parser = this.useOpenAI ? 'openai' : 'heuristic';
    const modelPart = this.useOpenAI ? `&model=${encodeURIComponent(this.selectedModel)}&max_completion_tokens=${encodeURIComponent(String(this.selectedMaxTokens))}` : '';

    // If the file is a binary doc (docx/pdf) we call the /extract-text
    // endpoint and display the extracted text, rather than POSTing the
    // binary to /parse-policy. This happens regardless of the "Use OpenAI"
    // checkbox because extraction of binary documents must go through
    // extract-text (server-side) to avoid confusion.
    const lower = (file.name || '').toLowerCase();
    const isDocx = lower.endsWith('.docx');
    const isPdf = lower.endsWith('.pdf');
    if (isDocx || isPdf) {
      // Acquire a friendly LLM-generated warning message from the server
      let warning = null;
      try{
        const wres = await fetch(`${this.apiUrl}/extract-warning?file_name=${encodeURIComponent(file.name)}`);
        const jw = await wres.json();
        warning = jw?.message || null;
      }catch(e){
        console.warn('failed to get extract warning from server', e);
      }
      if(!warning){
        warning = `The selected file (${file.name}) appears to be a binary document. We can extract its text using an external LLM (may incur costs). Proceed?`;
      }

      const ok = window.confirm(warning + '\n\nClick OK to proceed with LLM extraction, or Cancel to paste text manually.');
      if(!ok){ try{ input.value = ''; }catch{}; return; }

      this.pushLog('extract_text_start', { name: file.name, size: file.size, type: file.type });
      // show a spinner via busy flag while extracting
      this.busy = true;
      try{
        const r = await fetch(`${this.apiUrl}/extract-text`, { method: 'POST', body: fd });
        const resp = await r.json();
        if (resp.error){
          this.pushLog('extract_text_error', { name: file.name, error: resp.error, detail: resp.detail });
          if(resp.error === 'OPENAI_API_KEY not configured' || resp.error === 'openai_failed'){
            alert('OpenAI extraction is not available. Please open the document locally and copy & paste the text into the policy text box.');
          }
          this.parsedJsonError = resp.error || resp.detail || 'extract_failed';
        } else if (resp.job_id) {
          const jobId = resp.job_id;
          this.pushLog('extract_job_started', { name: file.name, job_id: jobId });
          // poll for status
          let done = false;
          while(!done){
            await new Promise(res => setTimeout(res, 1000));
            try{
              const s = await fetch(`${this.apiUrl}/extract-status?job_id=${encodeURIComponent(jobId)}`);
              const sj = await s.json();
              this.pushLog('extract_status', { job_id: jobId, status: sj.status, progress: sj.progress });
              if(sj.status === 'done'){
                done = true;
                const r2 = await fetch(`${this.apiUrl}/extract-result?job_id=${encodeURIComponent(jobId)}`);
                const jr = await r2.json();
                if(jr.error){
                  this.pushLog('extract_text_error', { name: file.name, error: jr.error });
                  alert('Extraction failed; please paste text manually.');
                } else {
                  this.pushLog('extract_text_success', { name: file.name, extracted_len: (jr.text||'').length });
                  this.policyText = jr.text || '';
                  this.uploadedFileContent = this.policyText;
                  this.parsedJsonText = '';
                }
              } else if(sj.status === 'error'){
                done = true;
                this.pushLog('extract_text_error', { name: file.name, job_id: jobId, error: sj.error });
                alert('Extraction failed; please paste text manually.');
              }
            }catch(err){
              this.pushLog('extract_status_error', { job_id: jobId, error: String(err) });
            }
          }
        } else {
          // legacy: server returned text directly
          this.pushLog('extract_text_success', { name: file.name, extracted_len: (resp.text||'').length });
          this.policyText = resp.text || '';
          this.uploadedFileContent = this.policyText;
          this.parsedJsonText = '';
        }
      }catch(err:any){
        console.error('extract-text failed', err);
        this.pushLog('extract_text_error', { name: file.name, error: String(err && err.message ? err.message : err) });
        alert('Extraction failed. Please open the document locally and copy & paste the text into the policy text box.');
        this.parsedJsonError = String(err && err.message ? err.message : err);
      } finally { this.busy = false; }
      try{ input.value = ''; }catch{}
      return;
    }

    // Otherwise fall back to existing behavior: POST the file to /parse-policy
    let j: any = null;
    try{
      this.pushLog('upload_start', { name: file.name, url: `${this.apiUrl}/parse-policy`, parser });
      if(this.useOpenAI){
            this.pushLog('openai_request_sent', { model: this.selectedModel, file: file.name, preview: (this.uploadedFileContent||'').slice(0,2000), length: (this.uploadedFileContent||'').length, max_completion_tokens: this.selectedMaxTokens });
      }
      let r;
      if(this.useOpenAI && this.simulateOpenAI){
        r = await fetch(`${this.apiUrl}/debug/openai-simulate?model=${encodeURIComponent(this.selectedModel)}`);
      } else {
        r = await fetch(`${this.apiUrl}/parse-policy?parser=${encodeURIComponent(parser)}${modelPart}`, { method:'POST', body: fd });
      }
      j = await r.json();
      try{
        const ds = this.datasetPath();
        if(ds && j && j.rules && Array.isArray(j.rules)){
          const cats = await fetch(`${this.apiUrl}/train/dataset/distinct?path=${encodeURIComponent(ds)}&field=category&limit=500`).then(r=>r.json());
          j = this.alignParsedCategoriesWithDataset(j, cats || []);
        }
      }catch(e){ /* ignore */ }
      this.pushLog('upload_success', { name: file.name, response_summary: { rules: j?.rules?.length ?? null, source: j?.source } });
      if(this.useOpenAI){
        // show full backend response for OpenAI-based parses
        this.parsedJsonText = JSON.stringify(j, null, 2);
        this.pushLog('openai_response_received', { model: this.selectedModel, response_preview: String(this.parsedJsonText).slice(0,2000) });
        const norm = this.normalizeParserResponse(j);
        if(!norm.error){ this.rulesDoc.set(norm.doc as any); this.parsedJsonError = null; }
        else { this.parsedJsonError = norm.error; }
      } else {
        const norm = this.normalizeParserResponse(j);
        if(norm.error){ this.parsedJsonError = norm.error; this.parsedJsonText = JSON.stringify(j, null, 2); }
        else { this.rulesDoc.set(norm.doc as any); this.parsedJsonText = JSON.stringify(norm.doc, null, 2); this.parsedJsonError = null; }
      }
    }catch(err:any){
      console.error('parse upload failed', err);
      this.pushLog('upload_error', { name: file.name, error: String(err && err.message ? err.message : err) });
      if(this.useOpenAI) this.pushLog('openai_error', { name: file.name, error: String(err && err.message ? err.message : err) });
      this.parsedJsonError = String(err && err.message ? err.message : err);
    }
    // reset input so selecting same file again will fire change
    try{ input.value = ''; }catch{}
  }

  // record a client-side log entry and also console.log for debugging
  pushLog(type: string, payload: any){
    const entry = { ts: new Date().toISOString(), type: `client:${type}`, payload };
    this.clientLogs.unshift(entry);
    console.log('CLIENT LOG', entry);
  }

  // Try to normalize various backend responses into a RuleDoc-like object
  normalizeParserResponse(resp: any): { doc?: any, error?: string }{
    if(!resp) return { error: 'empty_response' };
    let doc: any = null;
    // already shaped
    if(typeof resp === 'object'){
      if(Array.isArray(resp.rules)) doc = resp;
      else {
        // sometimes the server returns { parsed: { rules: [...] } }
        for(const k of Object.keys(resp)){
          const v = (resp as any)[k];
          if(Array.isArray(v) && v.length>0 && typeof v[0] === 'object' && ('name' in v[0] || 'condition' in v[0])){
            doc = { rules: v, source: resp.source || k };
            break;
          }
        }
        // maybe resp is itself an array of rules
        if(!doc && Array.isArray(resp) && resp.length>0 && typeof resp[0] === 'object' && ('name' in resp[0] || 'condition' in resp[0])){
          doc = { rules: resp };
        }
      }
    }
    // if not yet found, try to extract JSON from strings inside resp
    if(!doc){
      const candidates: string[] = [];
      if(typeof resp === 'string') candidates.push(resp);
      if(typeof resp === 'object'){
        if(typeof resp.extracted === 'string') candidates.push(resp.extracted);
        if(typeof resp.output === 'string') candidates.push(resp.output);
        if(typeof resp.text === 'string') candidates.push(resp.text);
        if(typeof resp.content === 'string') candidates.push(resp.content);
      }
      for(const s of candidates){
        if(!s) continue;
        // try direct JSON parse
        try{
          const p = JSON.parse(s);
          if(p && typeof p === 'object'){
            if(Array.isArray(p.rules)) { doc = p; break; }
            if(Array.isArray(p) && p.length>0 && typeof p[0] === 'object') { doc = { rules: p }; break; }
            for(const k of Object.keys(p)){
              const v = (p as any)[k];
              if(Array.isArray(v) && v.length>0 && typeof v[0] === 'object' && ('name' in v[0] || 'condition' in v[0])){
                doc = { rules: v, source: p.source || k }; break;
              }
            }
          }
        }catch{}
        // try to extract JSON substring
        const m = s.match(/\{[\s\S]*\}/);
        if(m){
          try{
            const p = JSON.parse(m[0]);
            if(p && (Array.isArray(p.rules) || Array.isArray(p))){
              if(Array.isArray(p.rules)) { doc = p; break; }
              if(Array.isArray(p)) { doc = { rules: p }; break; }
            }
          }catch{}
        }
      }
    }

    if(!doc) return { error: 'no_rules_found_in_response' };

    // Synthesize machine-readable condition expressions for rules that
    // have thresholds and categories but only contain human-friendly text
    const synthRuleCondition = (r: any) =>{
      try{
        if(r && r.condition && typeof r.condition === 'string'){
          const cond = r.condition.trim();
          // if already looks like code (contains comparison or boolean operators), skip
          if(/[><=]|\band\b|\bor\b|==|!=/i.test(cond)) return r.condition;
        }
        // If threshold and category present, synthesize a default numeric check
        if(r && (r.threshold !== undefined && r.threshold !== null) && r.category){
          const thr = Number(r.threshold);
          if(!isNaN(thr)){
            // Use > threshold to match 'exceeds the limit' wording
            return `category == '${r.category}' and amount > ${thr}`;
          }
        }
      }catch(e){ /* ignore */ }
      return r.condition;
    };

    if(doc && Array.isArray(doc.rules)){
      for(const rr of doc.rules){
        if(!rr.condition || typeof rr.condition === 'string'){
          const synthesized = synthRuleCondition(rr);
          if(synthesized && synthesized !== rr.condition){ rr.condition = synthesized; }
        }
      }
    }

    return { doc };
  }

  // Align parsed rule categories with categories present in the dataset.
  // This tries exact case-insensitive matches first, then substring matches.
  alignParsedCategoriesWithDataset(parsed: any, datasetCategories: string[]){
    if(!parsed || !Array.isArray(parsed.rules)) return parsed;
    const cats = (datasetCategories || []).map((c:any)=>String(c));
    const lowerMap: Record<string,string> = {};
    for(const c of cats){ lowerMap[c.toLowerCase()] = c; }
    const mapCategory = (val: string | undefined) =>{
      if(!val) return val;
      const s = String(val).trim();
      if(!s) return val;
      const low = s.toLowerCase();
      if(lowerMap[low]) return lowerMap[low];
      // try substring match
      for(const c of cats){ if(c.toLowerCase().includes(low) || low.includes(c.toLowerCase())) return c; }
      return val;
    };
    const out = JSON.parse(JSON.stringify(parsed));
    for(const r of out.rules||[]){
      // prefer explicit category field
      if(r.category){ r.category = mapCategory(r.category); }
      // also try to align category literals inside condition strings: look for quoted strings
      if(r.condition && typeof r.condition === 'string'){
        const m = r.condition.match(/(['"])([^'\"]+)\1/);
        if(m){
          const lit = m[2];
          const mapped = mapCategory(lit);
          if(mapped && mapped !== lit){
            // replace only the first occurrence of the literal inside quotes
            r.condition = r.condition.replace(m[0], m[1]+mapped+m[1]);
          }
        }
      }
    }
    return out;
  }

  applyParsedJson(){
    try{
      const parsed = JSON.parse(this.parsedJsonText);
      // basic validation
      if(!parsed || typeof parsed !== 'object' || !Array.isArray(parsed.rules)){
        this.parsedJsonError = 'Parsed JSON must be an object with a "rules" array';
        return;
      }
      for(const r of parsed.rules){
        if(!r.name || !r.condition){
          this.parsedJsonError = 'Each rule must have at least "name" and "condition" properties';
          return;
        }
      }
      this.parsedJsonError = null;
      // set into rulesDoc (preserve parser/source if present)
      this.rulesDoc.set(parsed as any);
    }catch(e:any){
      this.parsedJsonError = String(e.message || e);
    }
  }

  async train(){
    this.busy = true;
    try{
      // validate maxRows against dataset if dataset is explicitly selected or present
      if(this.selectedDataSource === 'csv' && !this.datasetPath()){
        alert('Selected CSV as source but no dataset CSV is available. Generate or select a CSV first.');
        this.busy = false; return;
      }
      if(this.selectedDataSource === 'db' && !(this.txTotal && this.txTotal>0)){
        alert('Selected DB as source but no transactions are loaded. Load transactions first.');
        this.busy = false; return;
      }

      if(this.datasetPath()){
        try{
          const ds = this.datasetPath() || '';
          const info = await fetch(`${this.apiUrl}/train/dataset/info?path=${encodeURIComponent(ds)}`).then(r=>r.json());
          if(this.maxRows && info.rows && this.maxRows > info.rows){
            alert(`max_rows (${this.maxRows}) cannot exceed dataset rows (${info.rows})`);
            this.busy = false;
            return;
          }
        }catch(e){ /* ignore */ }
      }

      // Build request according to explicit selection, otherwise fallback to auto behavior
      const bodyAny: any = { algo: this.algo, max_rows: this.maxRows };
      if(this.selectedDataSource === 'csv'){
        bodyAny.dataset_path = this.datasetPath();
      } else if(this.selectedDataSource === 'db'){
        bodyAny.db_query = this.buildDbQueryFromFilters();
      } else {
        // auto: prefer CSV if present, otherwise DB if rows exist
        if(this.datasetPath()){
          bodyAny.dataset_path = this.datasetPath();
        } else if(this.txTotal && this.txTotal>0){
          bodyAny.db_query = this.buildDbQueryFromFilters();
        }
      }
      // Optionally include parsed policy JSON so backend can incorporate rule-derived features
      if(this.rulesDoc()){
        bodyAny.rules_json = this.rulesDoc();
        bodyAny.include_policy_features = Boolean(this.includePolicyFeatures);
      }

      const r = await fetch(`${this.apiUrl}/train`, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify(bodyAny)
      });
      const j = await r.json();
      if(j && j.job_id){
        this.trainingJobId = j.job_id;
        this.pushLog('train_started', { job_id: j.job_id, algo: this.algo });
        // poll status
        while(true){
          await new Promise(res=>setTimeout(res, 1000));
          const st = await fetch(`${this.apiUrl}/train/status?job_id=${encodeURIComponent(j.job_id)}`).then(r=>r.json());
          this.trainingProgress = st.progress || 0;
          if(st.status === 'done'){
            this.trained.set(st.result);
            this.pushLog('train_completed', st.result || {});
            break;
          }
          if(st.status === 'failed'){
            alert('Training failed: ' + (st.error || 'unknown'));
            this.pushLog('train_failed', { job_id: j.job_id, error: st.error });
            break;
          }
        }
      } else {
        this.trained.set(j);
      }
    } finally { this.busy = false; }
  }

  async score(){
    // Decide scoring source: CSV if datasetPath present, otherwise DB if rows loaded.
    const ds = this.datasetPath();
    const wantsCsv = this.selectedDataSource === 'csv';
    const wantsDb = this.selectedDataSource === 'db';
    // Preflight checks depending on explicit source selection
    if(wantsCsv && !ds){ alert('CSV source selected but no dataset path available.'); this.pushLog('score_preflight_failed',{selected:'csv'}); return; }
    if(wantsDb && !(this.txTotal && this.txTotal>0)){ alert('DB source selected but no transactions loaded into DB.'); this.pushLog('score_preflight_failed',{selected:'db'}); return; }

    // If no explicit selection or Auto selected, prefer CSV when present, otherwise DB when loaded
    const useCsv = !!ds && (this.selectedDataSource === 'csv' || this.selectedDataSource === 'auto');
    const useDb = !useCsv && (this.selectedDataSource === 'db' || (this.selectedDataSource === 'auto' && this.txTotal && this.txTotal>0));

    if(!useCsv && !useDb){
      alert('No dataset available to score. Generate a CSV dataset or load transactions into the DB.');
      this.pushLog('score_preflight_failed', { datasetPath: ds, txTotal: this.txTotal, selected: this.selectedDataSource });
      return;
    }

    this.scoringBusy = true;
    this.busy = true;
    try{
      const body:any = {};
      if(useCsv) body.dataset_path = ds;
      else body.db_query = this.buildDbQueryFromFilters();
      if(this.rulesDoc()) body.rules_json = this.rulesDoc();
      this.pushLog('score_request_sent', { useCsv: !!body.dataset_path, useDb: !!body.db_query });
      const r = await fetch(`${this.apiUrl}/score`, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify(body)
      });
      const j: ScoreRow[] = await r.json();
      // normalize rows and apply policy rules client-side if parsed policy exists
      const rows: ScoreRow[] = (j || []).map((it:any) => {
        // ensure numeric fraud_score
        it.fraud_score = Number(it.fraud_score ?? 0);
        // ensure policy object exists
        if(!it.policy) it.policy = { compliant: true, violated_rules: [], reason: '' } as any;
        return it as ScoreRow;
      });

      // Apply parsed policy rules to each row (best-effort)
      const processed = this.applyPolicyToRows(rows);
      this.originalScores = processed;
      // derive category list for filters
      this.scoreCategories = Array.from(new Set(processed.map(s=>s.category).filter(Boolean)));
      // initialize filters cleared
      this.applyScoreFilters();
      this.pageIndex = 0;
    } finally { this.scoringBusy = false; this.busy = false; }
  }

  // Apply parsed rulesDoc to score rows; best-effort evaluation of simple conditions
  applyPolicyToRows(rows: ScoreRow[]): ScoreRow[]{
    const doc = this.rulesDoc();
    if(!doc || !Array.isArray(doc.rules) || doc.rules.length===0){
      // mark everything as compliant if no rules
      return rows.map(r => ({ ...r, policy: { compliant: true, violated_rules: [], reason: '' } }));
    }
    return rows.map(r => {
      const violated: string[] = [];
      for(const rule of doc.rules){
        try{
          if(this.evaluateRuleAgainstTx(rule, r)){
            // rule condition indicates a violation
            violated.push(rule.name || rule.violation_message || JSON.stringify(rule));
          }
        }catch(e){
          // ignore rule evaluation errors
        }
      }
      const compliant = violated.length===0;
      return { ...r, policy: { compliant, violated_rules: violated, reason: violated.join('; ') } };
    });
  }

  // Very small, conservative evaluator for rule.condition strings. Supports simple clauses joined by 'and'/'or'.
  evaluateRuleAgainstTx(rule: any, tx: any): boolean{
    const cond = (rule && rule.condition) || '';
    if(!cond) return false;
    // normalize
    const s = String(cond).trim();
    // split by OR first
    const orParts = s.split(/\s+or\s+/i).map(p=>p.trim());
    for(const orPart of orParts){
      const andParts = orPart.split(/\s+and\s+/i).map(p=>p.trim());
      let andOk = true;
      for(const clause of andParts){
        const c = clause.replace(/^\(|\)$/g, '').trim();
        // match patterns
        // amount comparisons
        let m = c.match(/^amount\s*(==|=|!=|<=|>=|<|>)\s*(\d+(?:\.\d+)?)$/i);
        if(m){
          const op = m[1]; const val = Number(m[2]);
          const aval = Number(tx.amount || 0);
          if(op === '==' || op === '=') andOk = andOk && (aval === val);
          else if(op === '!=') andOk = andOk && (aval !== val);
          else if(op === '<') andOk = andOk && (aval < val);
          else if(op === '<=') andOk = andOk && (aval <= val);
          else if(op === '>') andOk = andOk && (aval > val);
          else if(op === '>=') andOk = andOk && (aval >= val);
          else andOk = false;
          if(!andOk) break;
          continue;
        }
        // category == 'X' or category != 'X'
        m = c.match(/^([a-zA-Z_][a-zA-Z0-9_]*)\s*(==|=|!=)\s*(["'])(.*)\3$/i);
        if(m){
          const field = m[1]; const op = m[2]; const val = m[4];
          const fval = String(tx[field] ?? '');
          if(op === '==' || op === '=') andOk = andOk && (fval === val);
          else if(op === '!=') andOk = andOk && (fval !== val);
          else andOk = false;
          if(!andOk) break;
          continue;
        }
        // fallback: check for simple "amount > X" inside arbitrary clause
        m = c.match(/amount\s*>\s*(\d+(?:\.\d+)?)/i);
        if(m){ const val = Number(m[1]); if(!(Number(tx.amount||0) > val)){ andOk = false; break; } continue; }
        // unknown clause: be conservative and treat as not satisfied
        andOk = false; break;
      }
      if(andOk) return true;
    }
    return false;
  }

  applyScoreFilters(){
    let items = [...this.originalScores];
    if(this.filterCategory){ items = items.filter(i => i.category === this.filterCategory); }
    if(this.filterFraud){
      if(this.filterFraud === 'high') items = items.filter(i => i.fraud_score > 0.5);
      else if(this.filterFraud === 'med') items = items.filter(i => i.fraud_score > 0.2 && i.fraud_score <= 0.5);
      else if(this.filterFraud === 'low') items = items.filter(i => i.fraud_score <= 0.2);
    }
    if(this.filterPolicy){
      if(this.filterPolicy === 'violation') items = items.filter(i => i.policy && i.policy.compliant === false);
      else if(this.filterPolicy === 'ok') items = items.filter(i => i.policy && i.policy.compliant === true);
    }
    this.scores.set(items);
    this.dataSource.data = items;
  }

  clearScoreFilters(){ this.filterCategory=''; this.filterFraud=''; this.filterPolicy=''; this.applyScoreFilters(); }

  async loadLogs(){
    const r = await fetch(`${this.apiUrl}/logs?limit=20`);
    try{ this.logs = await r.json(); }catch(err:any){ this.pushLog('load_logs_failed', { error: String(err && err.message ? err.message : err) }); }
  }

  async createBot(){
    // construct bot name as filename_timestamp_model for easier identification
    const baseName = (this.uploadedFileName || 'policy').replace(/[^a-zA-Z0-9-_\.]/g, '_');
    const payload = { name: `${baseName}_${Date.now()}_${this.selectedModel}`, text: this.parsedJsonText || this.policyText, model: this.selectedModel, embed_model: this.selectedEmbedModel };
    const r = await fetch(`${this.apiUrl}/bots`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
    const j = await r.json();
    this.pushLog('bot_created', { id: j.id });
    await this.loadBots();
  }

  async loadBots(){
    const r = await fetch(`${this.apiUrl}/bots`);
    this.bots = await r.json();
  }

  async deleteBot(id: string){
    if(!confirm('Delete bot ' + id + '?')) return;
    try{
      const r = await fetch(`${this.apiUrl}/bots/${encodeURIComponent(id)}`, { method:'DELETE' });
      if(r.ok){
        this.pushLog('bot_deleted', { id });
        await this.loadBots();
      } else {
        const txt = await r.text();
        this.pushLog('bot_delete_failed', { id, error: txt });
        alert('Delete failed: '+txt);
      }
    }catch(e:any){
      alert('Delete failed: '+String(e && e.message ? e.message : e));
    }
  }

  logsVisible = false;
  expandedLogs = new Set<string>();
  toggleLogs(){ this.logsVisible = !this.logsVisible; }
  toggleLogDetail(l:any){ const id = l.id || l.ts; if(this.expandedLogs.has(id)) this.expandedLogs.delete(id); else this.expandedLogs.add(id); }
  isLogExpanded(l:any){ return this.expandedLogs.has(l.id || l.ts); }

  openChat(b: any){
    this.activeBot = b;
    this.chatMessages = [];
    // initialize per-chat overrides to the bot's defaults (or global defaults)
    this.botChatModelOverride = b?.model || this.selectedModel;
    this.botChatEmbedOverride = b?.embed_model || this.selectedEmbedModel;
  }
  // model overrides for active bot chat (allows trying different LMs without re-creating the bot)
  botChatModelOverride: string | null = null;
  botChatEmbedOverride: string | null = null;

  async sendBotMessage(text: string){
    if(!this.activeBot) return;
    this.chatMessages.push({ role:'user', text });
    // add thinking placeholder
    const placeholder = { role: 'bot', text: 'Thinking...', thinking: true };
    this.chatMessages.push(placeholder);
    const placeholderIdx = this.chatMessages.length - 1;
    try{
      const payload: any = { message: text };
      if(this.botChatModelOverride) payload.model = this.botChatModelOverride;
      if(this.botChatEmbedOverride) payload.embed_model = this.botChatEmbedOverride;
      const r = await fetch(`${this.apiUrl}/bots/${this.activeBot.id}/chat`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
      if(!r.ok){
        let errText = '';
        try{ errText = (await r.json()).detail || JSON.stringify(await r.json()); }catch{ errText = await r.text(); }
        this.chatMessages.splice(placeholderIdx,1);
        this.chatMessages.push({ role:'bot', text: 'Bot chat failed: '+errText });
        return;
      }
      const j = await r.json();
      // sanitize HTML if present
      let safeHtml: SafeHtml | null = null;
      if(j.formatted_html){
        try{ const sanitized = this.sanitizer.sanitize(SecurityContext.HTML, j.formatted_html) || ''; safeHtml = this.sanitizer.bypassSecurityTrustHtml(sanitized); }catch(e){ safeHtml = null }
      }
      this.chatMessages.splice(placeholderIdx,1,{ role:'bot', text: j.answer || j.formatted_text || '', formatted_html: safeHtml, structured: j.structured || j, sources: j.sources });
    }catch(e:any){
      this.chatMessages.splice(placeholderIdx,1);
      this.chatMessages.push({ role:'bot', text: 'Bot chat failed: '+String(e && e.message ? e.message : e) });
    }
  }

  async sendPolicyQuery(text: string, suppressUser: boolean = false){
    if(!text || !text.trim()) return;
    if(!suppressUser) this.chatPolicyMessages.push({ role:'user', text });
    // push a thinking placeholder and remember its index so we can replace it
    const placeholder = { role: 'bot', text: 'Thinking...', thinking: true };
    this.chatPolicyMessages.push(placeholder);
    const placeholderIdx = this.chatPolicyMessages.length - 1;
    try{
      const r = await fetch(`${this.apiUrl}/chat-policy`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ query: text, model: this.selectedModel, embed_model: this.selectedEmbedModel })});
      // handle non-2xx responses explicitly
      if(!r.ok){
        let errText = '';
        try{
          const errj = await r.json();
          errText = errj.detail || errj.error || JSON.stringify(errj);
        }catch(e){
          errText = await r.text();
        }
        // remove placeholder
        this.chatPolicyMessages.splice(placeholderIdx, 1);
        // if index not built, set flag to show Build Index button and remember the query
        if(String(errText).toLowerCase().includes('index_not_built') || String(errText).toLowerCase().includes('index not built')){
          this.indexMissing = true;
          this.pendingPolicyQuery = text;
          this.chatPolicyMessages.push({ role:'bot', text: 'Index not built. Click "Build Index" to prepare policy data for RAG queries.' });
        } else {
          this.chatPolicyMessages.push({ role:'bot', text: 'Policy chat failed: ' + errText });
        }
        return;
      }
      const j = await r.json();
      // build readable sources if provided
      let sources_readable = null;
      if(Array.isArray(j.sources)){
        sources_readable = j.sources.map((s:any, idx:number) => {
          try{ const p = s.source || s.id || ''; const name = String(p).split('/').pop(); return name; }catch{ return String(idx+1); }
        });
      }
      // sanitize HTML if present: first sanitize then mark as trusted SafeHtml
      let safeHtml: SafeHtml | null = null;
      if(j.formatted_html){
        try{
          const sanitized = this.sanitizer.sanitize(SecurityContext.HTML, j.formatted_html) || '';
          safeHtml = this.sanitizer.bypassSecurityTrustHtml(sanitized);
        }catch(e){
          safeHtml = null;
        }
      }
      // replace placeholder with real response, include structured payload if present
      this.chatPolicyMessages.splice(placeholderIdx, 1, { role:'bot', text: j.answer || j.formatted_text || '', formatted_html: safeHtml, structured: j.structured || j, sources: j.sources, sources_readable });
      // reset indexMissing on success
      this.indexMissing = false;
    }catch(err:any){
      // remove placeholder
      this.chatPolicyMessages.splice(placeholderIdx, 1);
      this.chatPolicyMessages.push({ role:'bot', text: 'Policy chat failed: '+String(err && err.message ? err.message : err) });
    }
  }

  async buildIndex(){
    // call backend to build index and show progress
    try{
      if(!confirm('Building the index will call the embeddings API and may incur cost. Proceed?')) return;
      this.busy = true;
      const r = await fetch(`${this.apiUrl}/index-policies`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ embed_model: 'text-embedding-3-small' })});
      const j = await r.json();
        if(j && j.ok){
        this.indexMissing = false;
        this.chatPolicyMessages.push({ role:'bot', text: `Index built: ${j.indexed} vectors.` });
        // if there was a pending query, retry it automatically
        if(this.pendingPolicyQuery){
          const q = this.pendingPolicyQuery;
          this.pendingPolicyQuery = null;
          // small delay so the user sees the index built message
            setTimeout(()=>{ this.sendPolicyQuery(q, true); }, 500);
        }
      } else {
        this.chatPolicyMessages.push({ role:'bot', text: `Index build response: ${JSON.stringify(j)}` });
      }
    }catch(e:any){
      this.chatPolicyMessages.push({ role:'bot', text: `Index build failed: ${String(e && e.message ? e.message : e)}` });
    }finally{ this.busy = false; }
  }

  async ngOnInit(){
    try{
      const r = await fetch(`${this.apiUrl}/healthz`);
      this.health = r.ok ? 'ok' : 'down';
    }catch{ this.health = 'down'; }
    // fetch parser config
    try{
      const rc = await fetch(`${this.apiUrl}/parse-config`);
      const cfg = await rc.json();
      // Do not auto-enable OpenAI. Leave it to the user toggle. Only pick default model.
      this.selectedModel = cfg.default_model || 'gpt-5-mini';
      this.pushLog('parse_config_loaded', { default_model: this.selectedModel });
    }catch(err:any){
      this.pushLog('parse_config_load_failed', { error: String(err && err.message ? err.message : err) });
    }
    // load available OpenAI models for bot creation (if any)
    try{
      const r = await fetch(`${this.apiUrl}/models`);
      const j = await r.json();
      // Accept either array of objects [{id,name}] or array of strings
      let models: string[] = [];
      if(Array.isArray(j)){
        for(const item of j){
          if(typeof item === 'string') models.push(item);
          else if(item && item.id) models.push(item.id);
        }
      } else if(j && Array.isArray((j as any).models)){
        models = (j as any).models.slice();
      }
      if(models.length>0){
        this.availableModels = models;
        // populate embedding model list; ensure default embedding model is present
        this.availableEmbedModels = Array.from(new Set([this.selectedEmbedModel].concat(models)));
      }
    }catch(e){ /* non-fatal */ }

    // load available training algorithms
    try{ await this.loadAlgos(); }catch(e){ /* ignore */ }
  }

  // Fetch and normalize available training algorithms. Exposed so user can refresh.
  async loadAlgos(){
    try{
      const r2 = await fetch(`${this.apiUrl}/train/algos`);
      let algosRaw: any = await r2.json();
      if(typeof algosRaw === 'string'){
        try{ algosRaw = JSON.parse(algosRaw); }catch{}
      }
      const algosList: string[] = [];
      const algosObjs: {id:string,label:string}[] = [];
      if(Array.isArray(algosRaw)){
        for(const it of algosRaw){
          if(typeof it === 'string'){
            algosList.push(it);
            algosObjs.push({ id: it, label: it });
          } else if(it && (it.id || it.name)){
            const id = (it.id || it.name).toString();
            const label = it.label || it.name || id;
            algosList.push(id);
            algosObjs.push({ id, label });
            this.algoLabels[id] = label;
          }
        }
      } else if(algosRaw && typeof algosRaw === 'object'){
        for(const k of Object.keys(algosRaw)){
          const label = String((algosRaw as any)[k]);
          algosList.push(k);
          algosObjs.push({ id: k, label });
          try{ this.algoLabels[k] = label; }catch{}
        }
      } else if(typeof algosRaw === 'string'){
        if(algosRaw) algosList.push(algosRaw);
      }
      this.availableAlgos = algosList;
      this.availableAlgosObjs = algosObjs;
      this.pushLog('algos_loaded', { count: this.availableAlgos.length, raw: algosRaw });
      if(this.availableAlgos.length>0 && !this.availableAlgos.includes(this.algo)) this.algo = this.availableAlgos[0];
    }catch(err:any){ this.pushLog('algos_load_failed', { error: String(err && err.message ? err.message : err) }); }
  }

  // model selection and compare
  selectedModel = 'gpt-5-mini';
  availableModels: string[] = [];
  availableEmbedModels: string[] = [];
  selectedEmbedModel = 'text-embedding-3-small';
  // training algos and labels
  // (availableAlgos and algo are declared earlier in the class; avoid duplicate
  // declarations which cause TS2300 Duplicate identifier errors)
  algoLabels: Record<string,string> = {
    'isolation_forest': 'Isolation Forest',
    'iforest': 'Isolation Forest (iforest alias)'
  };
  includePolicyFeatures: boolean = false;
  // Explicit data source selection for training: 'auto'|'csv'|'db'
  selectedDataSource: 'auto' | 'csv' | 'db' = 'auto';

  toggleDataSource(){
    const order: ('auto'|'csv'|'db')[] = ['auto','csv','db'];
    const idx = order.indexOf(this.selectedDataSource);
    const next = order[(idx+1) % order.length];
    this.selectedDataSource = next;
    this.pushLog('selected_data_source', { selected: next });
  }
  // (no diagnostics shown in UI)
  // styling classes for fraud badges (used by template)
  // Note: In component styles you can define .badge-low/.badge-med/.badge-high for colors.

  async compareParsers(){
    this.busy = true;
    try{
      this.pushLog('compare_parsers_start', { useOpenAI: this.useOpenAI, model: this.selectedModel });
      const text = this.uploadedFileContent || this.policyText || '';
      if(!text) return;
      const h = await fetch(`${this.apiUrl}/parse-policy?parser=heuristic`, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({text})}).then(r=>r.json());
      let o = null;
      if(this.useOpenAI){
        // Only call OpenAI if user enabled the toggle and there is sufficient content
        if(text.trim().length >= 20){
          try{
            this.pushLog('openai_request_sent', { model: this.selectedModel, preview: text.slice(0,2000), length: text.length, max_completion_tokens: this.selectedMaxTokens });
            if(this.simulateOpenAI){
              o = await fetch(`${this.apiUrl}/debug/openai-simulate?model=${encodeURIComponent(this.selectedModel)}`).then(r=>r.json());
            } else {
              o = await fetch(`${this.apiUrl}/parse-policy?parser=openai&model=${encodeURIComponent(this.selectedModel)}&max_completion_tokens=${encodeURIComponent(String(this.selectedMaxTokens))}`, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({text})}).then(r=>r.json());
            }
            this.pushLog('openai_response_received', { model: this.selectedModel, response: o });
          }catch(e){
            o = { error: String(e) };
            this.pushLog('openai_error', { error: String(e) });
          }
        } else {
          o = { note: 'openai_skipped_insufficient_content' };
        }
      } else {
        o = { note: 'openai_not_enabled' };
      }
      this.compareResult = { heuristic: h, openai: o };
      this.pushLog('compare_parsers_done', { heuristic_rules: h?.rules?.length ?? null, openai_note: o?.note ?? (o?.rules ? o?.rules?.length : null) });
    }finally{ this.busy = false; }
  }

  compareResult: any = null;

  ngAfterViewInit(): void {
    this.dataSource.paginator = this.paginator;
    this.dataSource.sort = this.sort;
  }

  // button handler to capture click before native file dialog opens
  chooseFileClicked(fileInput: HTMLInputElement){
    this.pushLog('choose_clicked', {});
    try{ fileInput.click(); }catch(e:any){ this.pushLog('choose_click_failed', { error: String(e && e.message ? e.message : e) }); }
  }

  // persist slider value
  saveSelectedMaxTokens(){
    try{ localStorage.setItem('OPENAI_MAX_COMPLETION_TOKENS', String(this.selectedMaxTokens)); }catch{}
  }

  onSliderChange(ev: any){
    const v = ev && ev.value !== undefined ? ev.value : ev;
    const n = Number(v) || 0;
    this.selectedMaxTokens = Math.max(1000, Math.min(50000, Math.floor(n/1000)*1000 || 1000));
    this.saveSelectedMaxTokens();
  }

  onNumberChange(v: any){
    let n = Number(v) || 0;
    if(n < 1000) n = 1000;
    if(n > 50000) n = 50000;
    // round to nearest 1000
    n = Math.round(n/1000)*1000;
    this.selectedMaxTokens = n;
    this.saveSelectedMaxTokens();
  }

  saveApiUrl(){
    this.apiUrl = (this.apiUrlInput || '').replace(/\/$/, '');
    localStorage.setItem('VITE_API_URL', this.apiUrl);
  }

  sortBy(field: keyof ScoreRow){
    if(this.sortField === field){
      this.sortDir = this.sortDir === 'asc' ? 'desc' : 'asc';
    } else {
      this.sortField = field;
      this.sortDir = 'asc';
    }
  }

  sortIcon(field: keyof ScoreRow){
    if(this.sortField !== field) return '';
    return this.sortDir === 'asc' ? '▲' : '▼';
  }

  totalPages(){
    const total = this.scores().length;
    return Math.max(1, Math.ceil(total / this.pageSize));
  }

  nextPage(){
    if(this.pageIndex + 1 < this.totalPages()) this.pageIndex++;
  }

  prevPage(){
    if(this.pageIndex > 0) this.pageIndex--;
  }

  // --- DB Transactions Browser ---
  txPage = 0;
  txPageSize = 25;
  txTotal = 0;
  txRows: any[] = [];
  txFilter: any = { employee_id:[], merchant:[], city:[], category:[], channel:[], card_id:[], min_amount:'', max_amount:'', start_ts:'', end_ts:'' };
  txSortBy: string = 'timestamp';
  txSortDir: 'asc' | 'desc' = 'desc';
  // distincts
  merchants: string[] = [];
  cities: string[] = [];
  categories: string[] = [];
  channels: string[] = [];

  async truncateTransactions(){
    await fetch(`${this.apiUrl}/db/transactions/truncate`, { method:'POST' });
    this.txPage = 0; this.txTotal = 0; this.txRows = [];
  }

  async loadTransactions(){
    const q = new URLSearchParams();
    q.set('page', String(this.txPage));
    q.set('page_size', String(this.txPageSize));
    q.set('sort_by', this.txSortBy);
    q.set('sort_dir', this.txSortDir);
    for(const k of ['employee_id','merchant','city','category','channel','card_id']){
      const v = this.txFilter[k];
      if(Array.isArray(v)){
        for(const it of v){ if(it && it.toString().trim()) q.append(k, it.toString()); }
      } else {
        const s = (v||'').toString().trim(); if(s) q.set(k, s);
      }
    }
    for(const k of ['min_amount','max_amount','start_ts','end_ts']){
      const v = (this.txFilter[k]||'').toString().trim(); if(v) q.set(k, v);
    }
    const r = await fetch(`${this.apiUrl}/db/transactions?${q.toString()}`);
    const j = await r.json();
    this.txRows = j.items || [];
    this.txTotal = j.total || 0;
    try{
      if(!this.userChangedMaxRows && this.txTotal) this.maxRows = this.txTotal;
    }catch{}
  }

  buildDbQueryFromFilters(){
    const normList = (v: any) => {
      if(Array.isArray(v)) return v.length ? v : undefined;
      if(v === null || v === undefined) return undefined;
      const s = String(v).trim();
      return s ? [s] : undefined;
    };
    return {
      employee_id: normList(this.txFilter.employee_id),
      merchant: normList(this.txFilter.merchant),
      city: normList(this.txFilter.city),
      category: normList(this.txFilter.category),
      channel: normList(this.txFilter.channel),
      card_id: normList(this.txFilter.card_id),
      min_amount: this.txFilter.min_amount || undefined,
      max_amount: this.txFilter.max_amount || undefined,
      start_ts: this.txFilter.start_ts || undefined,
      end_ts: this.txFilter.end_ts || undefined,
      sort_by: this.txSortBy || undefined,
      sort_dir: this.txSortDir || undefined,
    };
  }

  txTotalPages(){ return Math.max(1, Math.ceil(this.txTotal / this.txPageSize)); }
  txPrev(){ if(this.txPage>0){ this.txPage--; this.loadTransactions(); } }
  txNext(){ if(this.txPage+1<this.txTotalPages()){ this.txPage++; this.loadTransactions(); } }

  // Apply / Clear filters
  applyFilters(){ this.txPage = 0; this.loadTransactions(); }
  clearFilters(){ this.txFilter = { employee_id:[], merchant:[], city:[], category:[], channel:[], card_id:[], min_amount:'', max_amount:'', start_ts:'', end_ts:'' }; this.txPage = 0; this.loadTransactions(); }

  // header sort helper used by grid
  headerSort(field: string){
    if(this.txSortBy === field){ this.txSortDir = this.txSortDir === 'asc' ? 'desc' : 'asc'; }
    else { this.txSortBy = field; this.txSortDir = 'asc'; }
    this.txPage = 0; this.loadTransactions();
  }

  sortIconHeader(field: string){ if(this.txSortBy !== field) return ''; return this.txSortDir === 'asc' ? '▲' : '▼'; }

  async fetchDistinct(field: string){
    const r = await fetch(`${this.apiUrl}/db/transactions/distinct?field=${encodeURIComponent(field)}&limit=200`);
    const vals = await r.json();
    if(field==='merchant') this.merchants = vals; else if(field==='city') this.cities = vals; else if(field==='category') this.categories = vals; else if(field==='channel') this.channels = vals;
  }

  async loadCsvIntoDb(truncate: boolean){
    if(!this.datasetPath()) return;
    await fetch(`${this.apiUrl}/db/load-csv`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ path: this.datasetPath(), truncate })
    });
    this.txPage = 0;
    await this.loadTransactions();
  }
}
