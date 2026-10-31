"""Smoke test with a local mock Ollama and isolated test project."""
import os
import json
import tempfile
import threading
import subprocess
import sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
from playwright.sync_api import sync_playwright

HERE=Path(__file__).resolve().parents[1]
class Mock(BaseHTTPRequestHandler):
    def do_GET(self):
        b=json.dumps({'models':[{'name':'qwen2.5-coder:7b'}]}).encode()
        self.send_response(200);self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
    def do_POST(self):
        payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        assert payload['model']=='qwen2.5-coder:7b'
        b=(json.dumps({'message':{'content':'La IA local responde a tu pregunta.'}})+'\n'+json.dumps({'done':True})+'\n').encode()
        self.send_response(200);self.send_header('Content-Type','application/x-ndjson');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
    def log_message(self,*args):pass

def test_full_ui():
    html=(HERE/'BigAsereAI/Resources/index.html').read_text().replace('<link rel="stylesheet" href="/styles.css">','').replace('<script src="/app.js" defer></script>','')
    css=(HERE/'BigAsereAI/Resources/styles.css').read_text()
    js=(HERE/'BigAsereAI/Resources/app.js').read_text()
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
        page=browser.new_page(viewport={'width':1440,'height':920},device_scale_factor=1)
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.set_content(html);page.add_style_tag(content=css)
        page.evaluate(r"""() => {
            const project={configured:true,path:'/Users/demo/BigAsere',git:true,branch:'develop',status:'## develop\n M README.md',log:'9a7b1c primer commit',diffstat:'README.md | 2 ++',files:['README.md','asistente.py']};
            const settings={model:'qwen2.5-coder:7b',system_prompt:'Soy una IA local para Big Asere',project_path:project.path};
            let chats=[];let selected=null;
            window.fetch=async (url,options={}) => {
                const u=String(url),method=options.method||'GET'; let obj={};
                if(u==='/api/status') obj={ollama:{online:true,models:['qwen2.5-coder:7b']},settings};
                else if(u==='/api/chats'&&method==='GET')obj={chats:chats.map(c=>({id:c.id,title:c.title,updated:'hoy'}))};
                else if(u==='/api/chats'&&method==='POST'){selected={id:'mock123',title:'Nueva conversación',updated:'hoy',messages:[]};chats.push(selected);obj={chat:selected};}
                else if(u==='/api/project')obj=project;
                else if(u.startsWith('/api/project/file'))obj={content:'# Big Asere\nMaterial local de prueba.',path:'README.md'};
                else if(u==='/api/diagnostics')obj={version:'2.2.1',python:'3.13',git_available:true,project_path:project.path,data_path:'/Users/demo/Library/Application Support/Big Asere AI',conversations:chats.length,existing_scripts:{'asistente.py':true,'puente_big_asere.py':false}};
                else if(u==='/api/settings'&&method==='POST'){Object.assign(settings,JSON.parse(options.body));obj={settings};}
                else if(u.startsWith('/api/chats/')&&u.endsWith('/message')){
                    const data=JSON.parse(options.body);selected.messages.push({role:'user',content:data.content,files:data.files,git:data.include_git,mode:data.mode});
                    selected.messages.push({role:'assistant',content:'La IA local responde a tu pregunta.'});selected.title=data.content;
                    const encoder=new TextEncoder();let i=0;
                    const chunks=[encoder.encode(JSON.stringify({type:'delta',text:'La IA local responde a tu pregunta.'})+'\n'),encoder.encode(JSON.stringify({type:'done',error:null})+'\n')];
                    const reader = {read: async()=> i<chunks.length ? {done:false,value:chunks[i++]} : {done:true}};
                    return {ok:true,body:{getReader:()=>reader}};
                }
                else if(u.startsWith('/api/chats/')&&method==='GET')obj={chat:selected};
                else if(u.startsWith('/api/chats/')&&u.endsWith('/rename')){selected.title=JSON.parse(options.body).title;obj={ok:true}}
                else obj={ok:true};
                return {ok:true,json:async()=>obj};
            };
        }""")
        page.add_script_tag(content=js)
        page.wait_for_selector('#sideStatus:text("Ollama conectado")')
        assert page.locator('#dashFiles').inner_text()=='2'
        page.screenshot(path=str(HERE/'VISTA_PREVIA/ui_home_v2.png'),full_page=True)
        page.locator('#navProject').click();assert page.locator('#projectPath').inner_text()=='/Users/demo/BigAsere'
        page.screenshot(path=str(HERE/'VISTA_PREVIA/ui_project_v2.png'),full_page=True)
        page.locator('#navGit').click();assert 'primer commit' in page.locator('#gitLog').inner_text()
        page.screenshot(path=str(HERE/'VISTA_PREVIA/ui_git_v2.png'),full_page=True)
        page.locator('#attachGitToChat').click();assert page.locator('#gitToggle').is_checked()
        page.locator('#navFiles').click();assert page.locator('.file-item').count()==2
        page.locator('#fileSearch').fill('README');assert page.locator('.file-item').count()==1
        page.locator('.view-file').click();assert 'Material local de prueba' in page.locator('#fileContent').inner_text()
        page.locator('.file-item input').check();assert 'README.md' in page.locator('#contextStrip').inner_text()
        page.screenshot(path=str(HERE/'VISTA_PREVIA/ui_files_v2.png'),full_page=True)
        page.locator('#navSettings').click();page.locator('[data-tab="guide"]').click();assert 'Úsala en 3 pasos' in page.locator('#settingsGuide').inner_text()
        page.screenshot(path=str(HERE/'VISTA_PREVIA/ui_guide_v2.png'),full_page=True)
        page.locator('[data-tab="safety"]').click();assert 'Lo que NO puede hacer' in page.locator('#settingsSafety').inner_text()
        page.locator('[data-tab="diagnostic"]').click();page.wait_for_selector('.diagnostic-row')
        assert 'Encontrado, no integrado' in page.locator('#diagnosticList').inner_text()
        page.locator('#navChats').click();page.locator('[data-mode="auditoria"]').click();page.locator('#prompt').fill('Revisa el material')
        page.locator('#sendButton').click();page.wait_for_selector('.msg.assistant .msg-text:text("La IA local responde a tu pregunta.")')
        assert page.locator('.msg.user .msg-meta').count()==3
        page.wait_for_timeout(200)
        page.screenshot(path=str(HERE/'VISTA_PREVIA/ui_chat_v2.png'),full_page=True)
        assert not errors,errors
        browser.close()
