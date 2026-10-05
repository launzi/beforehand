import {renderSettings} from './core/settings-ui.js';
export async function initPopup({doc,chrome}) {
 await renderSettings({doc,chrome,root:doc.getElementById('controls')});
 const version=doc.getElementById('version');if(version)version.textContent=`v${chrome.runtime?.getManifest?.().version ?? ''}`;
}
if(globalThis.document && globalThis.chrome?.storage) void initPopup({doc:document,chrome});
