const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ChartData = require('../web/chart-data.js');
const nodes = new Map();
const element = id => {
 if (!nodes.has(id)) nodes.set(id, {value:'',textContent:'',innerHTML:'',clientWidth:900,querySelectorAll:()=>[]});
 return nodes.get(id);
};
class FixedDate extends Date {
 constructor(...args) { super(...(args.length ? args : ['2026-11-15T18:30:00Z'])); }
}
const context = vm.createContext({document:{getElementById:element},Intl,Date:FixedDate,ChartData});
const app = fs.readFileSync(require.resolve('../web/app.js'),'utf8').replace(/init\(\);\s*$/, '');
vm.runInContext(app+'\nstate.parameters={fuels:[]};',context);
element('date-input').value='2026-08-15';
element('trend-range').value='7';
vm.runInContext('renderTrend()',context);
assert.match(element('trend-subtitle').textContent,/2026-11-10 ถึง 2026-11-16/);
element('date-input').value='2026-09-01';
vm.runInContext('renderTrend()',context);
assert.match(element('trend-subtitle').textContent,/2026-11-10 ถึง 2026-11-16/);
element('trend-range').value='30';
vm.runInContext('renderTrend()',context);
assert.match(element('trend-subtitle').textContent,/2026-10-18 ถึง 2026-11-16/);
element('trend-range').value='custom';
element('trend-start').value='2026-08-13';
element('trend-end').value='2026-08-15';
vm.runInContext('renderTrend()',context);
assert.match(element('trend-subtitle').textContent,/2026-08-13 ถึง 2026-08-15/);
console.log('Dashboard trend: Thai current day, map-date independence, 7/30 days and custom dates passed.');
