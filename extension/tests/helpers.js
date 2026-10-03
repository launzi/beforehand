export class Store {
 constructor(data={}) {this.data=structuredClone(data);}
 async get(keys) {return Object.fromEntries((keys==null?Object.keys(this.data):[].concat(keys)).filter(k=>k in this.data).map(k=>[k,structuredClone(this.data[k])]));}
 async set(value) {Object.assign(this.data,structuredClone(value));}
 async remove(keys) {for(const k of [].concat(keys)) delete this.data[k];}
 async clear() {this.data={};}
}
export const consent=()=>({consent:{accepted:true,version:4}});
export const quote=(overrides={})=>({seller:'Munteok',item:{title:'Anua Toner 250ml',priceKrw:18000,link:'https://shop.example/product'},destination:'US',currency:'USD',
 payNow:{total:30,totalKrw:42000,itemKrw:18000,shippingKrw:18000,serviceFeeKrw:4000,paymentFeeKrw:2000,fxRate:1400},
 dutyOnDelivery:{estimate:2,note:'Paid on delivery',lines:[{label:'Duty',rate:'10%',amount:2,source:'Engine fixture'}]},
 totalCost:32,localPrice:null,verdict:null,warnings:[],quoteToken:'FAKE_QUOTE_TOKEN_0123456789',quoteExpiresAt:'2099-01-01T00:00:00.000Z',...overrides});
export const rpc=data=>({jsonrpc:'2.0',id:1,result:{structuredContent:data}});
export const response=data=>({ok:true,status:200,headers:{get:()=> 'application/json'},json:async()=>rpc(data)});
