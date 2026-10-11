// Small deterministic DOM adapter, no parsing and no network.
export class Element {
 constructor(tag,doc) {this.tagName=tag;this.ownerDocument=doc;this.children=[];this.listeners={};this.attributes={};this.style={};this.value='';this.hidden=false;this.disabled=false;this._text='';}
 set textContent(v) {this._text=String(v);this.children=[];}
 get textContent() {return this._text+this.children.map(c=>c.textContent ?? c).join('');}
 append(...nodes) {for(const n of nodes) {this.children.push(n);if(typeof n==='object') n.parent=this;}}
 replaceChildren(...nodes) {this._text='';this.children=[];this.append(...nodes);}
 remove() {this.removed=true;if(this.parent) this.parent.children=this.parent.children.filter(n=>n!==this);}
 attachShadow(options) {this.shadowOptions=options;this.testShadow=new Element('shadow',this.ownerDocument);return this.testShadow;}
 addEventListener(event,fn) {this.listeners[event]=fn;}
 setAttribute(k,v) {this.attributes[k]=String(v);}
 getAttribute(k) {return this.attributes[k] ?? null;}
 focus() {this.ownerDocument.activeElement=this;}
 async fire(event='click') {if(!this.disabled) return this.listeners[event]?.({preventDefault(){}});}
 click() {return this.fire();}
}
export function documentFake() {
 const doc={visibilityState:'visible',createElement:tag=>new Element(tag,doc),createElementNS:(_,tag)=>new Element(tag,doc),getElementById:id=>all(doc.body).find(n=>n.id===id)};
 doc.body=new Element('body',doc);return doc;
}
export const all=root=>[root,...root.children.flatMap(n=>typeof n==='object'?all(n):[])];
export const findText=(root,text)=>all(root).find(n=>n.tagName==='button' && n.textContent===text);
