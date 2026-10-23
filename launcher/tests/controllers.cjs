const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createHarness } = require('./harness.cjs');
(async () => {
  const h = await createHarness({viewport:{width:1280,height:1000}});
  const {page, open} = h;
  let checks = 0;
  const ok = (value, name) => { assert.ok(value, name); checks++; };
  try {
    await page.evaluate(() => {
      const app = document.createElement('div'); app.id='app'; document.body.prepend(app);
      app.innerHTML='<nav id="side"><div class="brand"><div class="brand-mark">C</div><div><div class="brand-name">CoastLink</div><div class="brand-sub">0.6.1 rollback</div></div></div><button class="nav-item">Play</button><button class="nav-item">Online</button><button class="nav-item" aria-current="page">Controllers</button><button class="nav-item">Display & speed</button><button class="nav-item">Audio</button><button class="nav-item">Session & Verify</button><button class="nav-item">Updates & build</button></nav>';
      app.append(document.querySelector('#view'));
      const fonts=document.createElement('link'); fonts.rel='stylesheet'; fonts.href='/fonts.css'; document.head.append(fonts);
      window.mockSettings.controller={keyboard_player:'none'};
      window.mockSettings.keyboard_bindings={A:'Z', B:'X', X:'C', Y:'V', L:'Q', R:'E', ZL:'A', ZR:'S', MINUS:'BACKSPACE', PLUS:'ENTER'};
      window.mockResponses['pads.devices']=[{guid:'a'.repeat(32), name:'Xbox Wireless Controller',kind:'Xbox One',type_key:'xbox',gamepad:true,player:1}];
      window.mockResponses['pads.config']={general:{deadzone:'0.1',outer_zone:'0.98',rumble:'on',rumble_strength:'1',trigger_threshold:'0.33'},types:{xbox:{'map.a':'south',deadzone:'0.18'}},devices:{},players:Object.fromEntries(Array.from({length:8},(_,i)=>[String(i+1),i===0?'auto':'none']))};
      window.mockResponses['pads.adapters']=[]; window.mockResponses['pads.profiles']={profiles:[]};
      window.mockResponses['pads.watch']={}; window.mockResponses['pads.rumble']={ok:true};
      const old=window.mockCall;
      window.mockCall=async(cmd,args={})=>{
        const result=await old(cmd,args);
        if(cmd==='pads.config' && args.save){
          Object.assign(mockResponses[cmd].players,args.save.players);
          for(const [guid,changes] of Object.entries(args.save.devices))Object.assign(mockResponses[cmd].devices[guid]||={},changes);
          return structuredClone(mockResponses[cmd]);
        }
        return result;
      };
      window.sendPad=(state)=>{for(const f of mockListeners.get('pad')||[])f({guid:'a'.repeat(32),buttons:[],axes:{},...state});};
    });
    await open('controllers');
    ok(await page.locator('.pad-svg.family-xbox').count()===1,'Xbox diagram');
    ok(await page.locator('[data-bind="A"]').innerText()==='A','Inherited type binding shown');
    ok(await page.locator('#dz').inputValue()==='0.18','Inherited deadzone shown');
    ok(await page.locator('#save').isDisabled(),'No spurious pending settings');
    await page.locator('[data-bind="B"]').click();
    await page.evaluate(()=>sendPad({buttons:['north']}));
    ok(await page.locator('[data-bind="B"]').innerText()==='Cancel','Initial held input establishes baseline');
    await page.keyboard.press('Escape');
    await page.evaluate(()=>sendPad({buttons:['start','back','south'],axes:{leftx:32767,lefty:-32768,righttrigger:14000}}));
    ok(await page.locator('[data-source="start"].lit').count()===1,'Menu lights');
    ok(await page.locator('[data-source="back"].lit').count()===1,'View lights');
    ok(await page.locator('[data-source="righttrigger"].lit').count()===1,'Threshold matches setting');
    ok((await page.locator('[data-stick="left"]').getAttribute('transform')).includes('13.00 -13.00'),'Stick follows both axes');
    ok(await page.locator('[data-bind="A"]').evaluate(e=>e.closest('.bind-row').classList.contains('input-active')),'Mapped action lights');
    await page.evaluate(()=>sendPad({}));
    await page.locator('[data-bind="B"]').click();
    await page.evaluate(()=>sendPad({buttons:['north']}));
    ok(await page.locator('[data-bind="B"]').innerText()==='Y','First fresh binding press captured');
    ok(await page.evaluate(()=>mockSuspend)===0,'Navigation suspension released');
    ok(await page.evaluate(()=>!mockCalls.some(c=>c.cmd==='pads.config'&&c.args.save)),'Binding waits for explicit save');
    await page.locator('#save').click();
    ok(await page.evaluate(()=>mockCalls.some(c=>c.cmd==='pads.config'&&c.args.save?.devices?.['a'.repeat(32)]?.['map.b']==='north')),'Binding saved as native source');
    await page.locator('[data-bind="A"]').click();
    await page.keyboard.press('Escape');
    ok(await page.evaluate(()=>mockSuspend)===0,'Escape cancels capture');
    await page.evaluate(()=>sendPad({connected:false}));
    ok((await page.locator('#conn').innerText()).includes('Disconnected'),'Disconnect shown');
    ok(await page.locator('.pad-control.lit').count()===0,'No stuck lights after disconnect');
    await page.screenshot({path:path.join(process.env.COASTLINK_TEST_OUTPUT || require('node:os').tmpdir(),'controller-preview-xbox.png'),fullPage:true});
    for (const [kind,type,css] of [['PlayStation 5','playstation','ps'],['Switch Pro','switch','nin'],['GameCube','gamecube','gc']]) {
      await page.evaluate(({kind,type})=>{Object.assign(mockResponses['pads.devices'][0],{kind,type_key:type,name:kind+' controller'});}, {kind,type});
      await open('controllers');
      ok(await page.locator('.family-'+css).count()===1,kind+' adaptive diagram');
      const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth || [...document.querySelectorAll('.controller-workspace .card')].some(e=>e.scrollWidth>e.clientWidth+2));
      ok(!overflow,kind+' no horizontal clipping');
    }
    await page.screenshot({path:path.join(process.env.COASTLINK_TEST_OUTPUT || require('node:os').tmpdir(),'controller-preview-gamecube.png'),fullPage:true});
    await page.evaluate(()=>{mockResponses['pads.devices'][0].gamepad=false;mockResponses['pads.devices'][0].kind='Unknown';mockResponses['pads.devices'][0].type_key='joystick';});
    await open('controllers');
    ok(await page.locator('.raw-preview').count()===1,'Raw joystick numbers shown honestly');
    ok(await page.locator('[data-bind="A"]').innerText()==='Button 1','Raw native defaults');
    await page.evaluate(()=>sendPad({raw:true,buttons:['button1']}));
    ok(await page.locator('[data-source="button1"].lit').count()===1,'Raw source lights');
    await page.evaluate(()=>{mockSettings.controller.keyboard_player='1';});
    await open('controllers');
    ok(await page.locator('.keyboard-preview').count()===1,'Keyboard preview');
    await page.keyboard.down('z');
    ok(await page.locator('[data-key-control="A"].lit').count()===1,'Keyboard lights');
    await page.keyboard.up('z');
    ok(await page.locator('[data-key-control="A"].lit').count()===0,'Keyboard release clears');
    await page.locator('#dev').selectOption('none');
    ok(await page.locator('.keyboard-preview').count()===0,'Nobody removes explicit keyboard');
    await page.locator('#save').click();
    const keyboardPatch=await page.evaluate(()=>mockCalls.filter(c=>c.cmd==='settings.save').at(-1).args.settings);
    ok(Object.keys(keyboardPatch.controller).join()==='keyboard_player'&&!keyboardPatch.keyboard_bindings,'Assignment saves no unrelated settings');
    await page.evaluate(()=>{mockResponses['pads.devices']=[];mockSettings.controller.keyboard_player='auto';mockResponses['pads.config'].players['1']='auto';});
    await open('controllers');
    ok(await page.locator('.keyboard-preview').count()===1,'Automatic keyboard chooses first usable slot');
    await page.locator('#dev').selectOption('none');
    ok(await page.locator('.keyboard-preview').count()===0,'Nobody disables automatic keyboard too');
    await page.locator('#save').click();
    ok(await page.evaluate(()=>mockSettings.controller.keyboard_player==='none'),'Automatic keyboard disable persists');
    ok(h.errors.length===0,'No page errors: '+h.errors.join(';'));
    // Exercise the real navigation module while a gamepad reports every action held.
    await page.route('https://coastlink.test/js/nav-policy.js',route=>route.fulfill({contentType:'text/javascript',body:fs.readFileSync(path.join(__dirname,'../ui/js/nav.js'))}));
    await page.evaluate(async()=>{
      const nav=await import('/js/nav-policy.js');
      document.querySelector('#view').innerHTML='<div id="nav-items"></div><button id="nav-probe">Keep my settings</button><input id="nav-range" type="range" value="50">';
      window.navClicks=0;document.querySelector('#nav-probe').onclick=()=>window.navClicks++;
      document.querySelector('#nav-probe').focus();
      Object.defineProperty(navigator,'getGamepads',{configurable:true,value:()=>[{buttons:Array.from({length:16},()=>({pressed:true,value:1})),axes:[1,1]}]});
      nav.installNavigation();
      window.dispatchEvent(new Event('gamepadconnected'));
      await new Promise(r=>setTimeout(r,350));
    });
    ok(await page.evaluate(()=>navClicks===0&&document.activeElement.id==='nav-probe'&&document.querySelector('#nav-range').value==='50'),'Held controller never clicks, moves focus, or changes values');
    fs.writeFileSync(path.join(process.env.COASTLINK_TEST_OUTPUT || require('node:os').tmpdir(),'controller-ui-results.json'),JSON.stringify({passed:true,checks,headless:true,nativeGameLaunched:false},null,2));
    console.log(JSON.stringify({passed:true,checks}));
  } finally {await h.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
