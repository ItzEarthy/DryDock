(function initSpoolList(root){
        const container = root.querySelector('#spool-list');
        if (!container) return;

        const searchEl = root.querySelector('#spool-search');
        const sortEl = root.querySelector('#spool-sort');
        const clearBtn = root.querySelector('#spool-clear');
        const compactToggle = root.querySelector('#compact-toggle');
        const mmuFilter = root.querySelector('#mmu-filter');
        const selectAll = root.querySelector('#select-all');
        const bulkArchive = root.querySelector('#bulk-archive');
        const bulkDelete = root.querySelector('#bulk-delete');

        // Restore state from sessionStorage
        if (searchEl && sessionStorage.getItem('dd-spool-search')) searchEl.value = sessionStorage.getItem('dd-spool-search');
        if (sortEl && sessionStorage.getItem('dd-spool-sort')) sortEl.value = sessionStorage.getItem('dd-spool-sort');
        if (mmuFilter && sessionStorage.getItem('dd-spool-mmu') === 'true') mmuFilter.checked = true;

        function setCompact(on){
            if (on) {
                container.classList.add('compact-mode');
                sessionStorage.setItem('dd-spool-compact', 'true');
            } else {
                container.classList.remove('compact-mode');
                sessionStorage.setItem('dd-spool-compact', 'false');
            }
        }
        
        if (sessionStorage.getItem('dd-spool-compact') === 'true') {
            setCompact(true);
        }

        if (compactToggle) {
            compactToggle.addEventListener('click', ()=> setCompact(!container.classList.contains('compact-mode')));
        }

        function filterAndSort() {
            const q = (searchEl?.value || '').trim().toLowerCase();
            const mmuOn = mmuFilter ? mmuFilter.checked : false;
            const items = Array.from(container.querySelectorAll('.spool-item'));

            // Save state
            if (searchEl) sessionStorage.setItem('dd-spool-search', searchEl.value);
            if (sortEl) sessionStorage.setItem('dd-spool-sort', sortEl.value);
            if (mmuFilter) sessionStorage.setItem('dd-spool-mmu', mmuFilter.checked);

            // Filter (incorporate both search and MMU rules)
            items.forEach(item => {
                const text = item.getAttribute('data-search') || '';
                const matchesSearch = (!q || text.indexOf(q) !== -1);
                const matchesMMU = (!mmuOn || item.dataset.loadedInMmu === 'true');
                
                item.style.display = (matchesSearch && matchesMMU) ? '' : 'none';
            });

            // Sort
            const mode = sortEl?.value || 'default';
            let toSort = items.filter(i => i.style.display !== 'none');
            if (mode === 'material-asc') {
                toSort.sort((a,b)=> (a.dataset.material || '').localeCompare(b.dataset.material || ''));
            } else if (mode === 'remaining-desc') {
                toSort.sort((a,b)=> Number(b.dataset.remaining) - Number(a.dataset.remaining));
            } else if (mode === 'remaining-asc') {
                toSort.sort((a,b)=> Number(a.dataset.remaining) - Number(b.dataset.remaining));
            }

            // Append in sorted order (non-sorted keeps server order)
            if (mode !== 'default') {
                toSort.forEach(node => container.appendChild(node));
            }
            
            // Re-evaluate bulk actions visibility if selection was hidden
            updateBulkActionsVisibility();
        }

        if (searchEl) searchEl.addEventListener('input', filterAndSort);
        if (sortEl) sortEl.addEventListener('change', filterAndSort);
        if (mmuFilter) mmuFilter.addEventListener('change', filterAndSort);
        
        if (clearBtn) clearBtn.addEventListener('click', ()=>{ 
            if (searchEl) { searchEl.value=''; sessionStorage.removeItem('dd-spool-search'); }
            if (sortEl) { sortEl.value='default'; sessionStorage.removeItem('dd-spool-sort'); }
            if (mmuFilter) { mmuFilter.checked = false; sessionStorage.removeItem('dd-spool-mmu'); }
            filterAndSort(); 
        });

        function updateBulkActionsVisibility() {
            const visibleChecked = Array.from(root.querySelectorAll('.spool-select:checked'))
                .filter(cb => cb.closest('.spool-item')?.style.display !== 'none');
            
            const actionsContainer = root.querySelector('#bulk-actions-container');
            if (actionsContainer) {
                if (visibleChecked.length > 0) {
                    actionsContainer.classList.remove('hidden');
                } else {
                    actionsContainer.classList.add('hidden');
                }
            }
        }

        if (selectAll) selectAll.addEventListener('change', ()=>{
            const checked = selectAll.checked;
            container.querySelectorAll('.spool-item').forEach(item => {
                if (item.style.display !== 'none') {
                    const cb = item.querySelector('.spool-select');
                    if (cb) cb.checked = checked;
                }
            });
            root.querySelectorAll('.spool-select').forEach(cb=> cb.classList.remove('hidden'));
            updateBulkActionsVisibility();
        });

        root.querySelectorAll('.spool-select').forEach(cb => {
            cb.addEventListener('change', updateBulkActionsVisibility);
        });

        async function performBulk(action){
            const selected = Array.from(root.querySelectorAll('.spool-select:checked'))
                .filter(cb => cb.closest('.spool-item')?.style.display !== 'none')
                .map(cb=> cb.closest('.spool-item')?.dataset?.spoolId)
                .filter(Boolean);
                
            if (!selected.length) return alert('No spools selected');
            if (!confirm(`Perform ${action} on ${selected.length} spools?`)) return;
            
            for (const id of selected){
                try{
                    const fd = new URLSearchParams(); fd.append('action', action); fd.append('spool_id', id);
                    await fetch('/filaments/spoolman/action', { method: 'POST', body: fd });
                }catch(e){ console.error(e); }
            }
            
            const wrapper = document.getElementById('spool-list-wrapper');
            if (wrapper){
                try{ const res = await fetch('/filaments/partials/spool_list'); if (res.ok){ wrapper.innerHTML = await res.text(); } else location.reload(); }
                catch(e){ location.reload(); }
            } else location.reload();
        }

        if (bulkArchive) bulkArchive.addEventListener('click', ()=> performBulk('archive'));
        if (bulkDelete) bulkDelete.addEventListener('click', ()=> performBulk('remove'));

        container.querySelectorAll('.spool-item').forEach(item=>{
            if (item.querySelector('.compact-menu-btn')) return;
            const menu = document.createElement('button');
            menu.className = 'compact-menu-btn btn btn-ghost btn-sm';
            menu.type = 'button';
            menu.textContent = '\u22EF';
            menu.title = 'Actions';
            menu.style.marginRight = '0.5rem';
            menu.addEventListener('click', ()=>{
                const actions = item.querySelector('.spool-actions');
                if (actions) actions.classList.toggle('show');
            });
            item.insertBefore(menu, item.firstChild);
        });

        function focusByRfid(uid){
            if (!uid) return;
            const clean = String(uid).replace(/^"|"$/g,'').trim();
            const node = Array.from(container.querySelectorAll('.spool-item')).find(it=> (it.dataset.rfid||'').includes(clean) || (it.dataset.search||'').includes(clean.toLowerCase()));
            if (node){
                node.scrollIntoView({behavior:'smooth', block:'center'});
                node.classList.add('spool-highlight');
                setTimeout(()=> node.classList.remove('spool-highlight'), 3000);
            }
        }
        
        try{ const params = new URLSearchParams(window.location.search); const r = params.get('rfid'); if (r) focusByRfid(r); }catch(e){}
        
        if (!window.rfidListenerAdded) {
            document.addEventListener('rfid-scanned', (e)=>{ if (e.detail && e.detail.uid) focusByRfid(e.detail.uid); });
            window.rfidListenerAdded = true;
        }

        filterAndSort();
        
    })(document.currentScript ? document.currentScript.parentElement : document);
