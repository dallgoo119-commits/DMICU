import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
const root=new URL('../',import.meta.url);
const read=file=>fs.readFileSync(new URL(file,root),'utf8');
test('site pages have valid scripts and existing local links',()=>{
  for(const file of ['index.html','policy.html','methodology.html','gwangju_emergency_map.html']){
    const html=read(file);
    for(const [,script] of html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi)) assert.doesNotThrow(()=>new vm.Script(script),file);
    for(const [,url] of html.matchAll(/(?:src|href)="([^"]+)"/g)){
      if(/^(?:https?:|#|mailto:|tel:)/.test(url))continue;
      assert.ok(fs.existsSync(new URL(url.split(/[?#]/)[0],root)),`${file}: ${url}`);
    }
  }
  new vm.Script(read('assets/dashboard.js'));
});
test('initial map does not embed the historical database',()=>{
  const html=read('gwangju_emergency_map.html');
  assert.ok(Buffer.byteLength(html)<500000);
  assert.match(html,/const HISTORY=\[\];/);
  assert.match(html,/const NATIONAL_HISTORY=\[\];/);
  assert.ok(fs.readdirSync(new URL('data/trends/national/',root)).length>400);
});
test('policy numbers are classified and visitors are not inflated',()=>{
  const html=read('policy.html');
  assert.doesNotMatch(html,/PUBLIC_BASELINE_VISITORS/);
  assert.match(html,/setText\('totalVisitors', stats.total\)/);
  assert.match(html,/확정 비율로 사용하지 않습니다/);
  assert.match(html,/검증 대기/);
  assert.doesNotMatch(html,/<iframe class="map-frame"/);
});

test('current snapshots are unique, coherent and backed by trend files',()=>{
  const html=read('gwangju_emergency_map.html');
  const array=name=>JSON.parse(html.match(new RegExp(`const ${name}=(\\[[^\\n]*\\]);`))[1]);
  const local=array('DATA'), national=array('NATIONAL_CURRENT');
  const meta=array('LOCALMETA')[0], natMeta=array('NATMETA')[0];
  assert.equal(local.length,meta.total);
  assert.equal(national.length,natMeta.total);
  for(const [scope,rows,codeKey] of [['local',local,'code'],['national',national,'c']]){
    assert.equal(new Set(rows.map(row=>row[codeKey])).size,rows.length);
    for(const row of rows){
      const code=row[codeKey];
      const records=JSON.parse(read(`data/trends/${scope}/${encodeURIComponent(encodeURIComponent(code))}.json`));
      assert.ok(records.length>0);
      assert.ok(records.every(record=>record.code===code));
      assert.equal(new Set(records.map(record=>record.date)).size,records.length);
    }
  }
  for(const row of national){
    assert.ok(Number.isSafeInteger(row.a)&&Number.isSafeInteger(row.o)&&row.o>0&&row.a<=row.o);
    assert.equal(row.s,Math.round((row.o-row.a)/row.o*1000)/10);
  }
});
