import {useState} from "react";
import "./style.css";

const agents=[
 ["Interpreter","Understanding your objective"],
 ["Planner","Ready"],
 ["Researcher","Evidence-aware"],
 ["Builder","Waiting"],
 ["Critic","Independent"],
 ["Verifier","Independent verification"]
];

export default function App(){
 const [text,setText]=useState("");
 const [messages,setMessages]=useState([{who:"System",text:"Tell me what you want to accomplish. I will ask if something materially changes the result."}]);
 function send(){
  if(!text.trim())return;
  setMessages(m=>[...m,{who:"You",text},{who:"Interpreter",text:"Objective received. I will preserve your original request and make assumptions explicit."}]);
  setText("");
 }
 return <div className="app">
  <aside className="left"><h1>NEXUS</h1><button>＋ NEW TASK</button><div className="nav active">Current project</div><div className="nav">Artifacts</div><div className="nav">Research</div><div className="nav">Memory</div></aside>
  <main><header><div><b>ACTIVE WORKSPACE</b><small>Collaborative multi-agent system</small></div><span>● HEALTH MONITORED</span></header>
  <section className="conversation">{messages.map((m,i)=><article key={i} className={m.who==="You"?"user":""}><b>{m.who}</b><p>{m.text}</p></article>)}</section>
  <footer><input value={text} onChange={e=>setText(e.target.value)} onKeyDown={e=>e.key==="Enter"&&send()} placeholder="What do you want the system to accomplish?"/><button onClick={send}>SEND</button></footer></main>
  <aside className="right"><h3>AGENTS</h3>{agents.map(a=><div className="agent" key={a[0]}><b>{a[0]}</b><small>{a[1]}</small></div>)}<h3>SYSTEM</h3><div className="metric">CPU <b>MONITORED</b></div><div className="metric">MEMORY <b>MONITORED</b></div><div className="metric">GPU <b>ADMISSION-AWARE</b></div></aside>
 </div>
}
