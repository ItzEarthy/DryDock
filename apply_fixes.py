import re

def update_file(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        content = f.read()

    # SVG Icons
    tag_svg = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="inline-block relative -top-[1px] mr-1"><path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><line x1="7" y1="7" x2="7.01" y2="7"/></svg>'
    loc_svg = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="inline-block relative -top-[1px] mr-1 text-[#35AB57]"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>'
    box_svg = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="inline-block relative -top-[1px] mr-1"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/></svg>'
    hot_svg = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="inline-block relative -top-[1px] mr-1 text-orange-500"><path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z"/></svg>'
    bed_svg = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="inline-block relative -top-[1px] mr-1 text-blue-400"><rect x="2" y="7" width="20" height="10" rx="2" ry="2"/><line x1="2" y1="17" x2="22" y2="17"/><line x1="6" y1="21" x2="6" y2="17"/><line x1="18" y1="21" x2="18" y2="17"/></svg>'

    # 1. Update location and lot icons
    content = content.replace(
        '''{% if location %} · <span class="text-[var(--text-primary)]">Loc: {{ location }}</span>{% endif %}''',
        f'''{{% if location %}} <span class="flex items-center text-[var(--color-sand)] ml-2" title="Location">{loc_svg}{{{{ location }}}}</span>{{% endif %}}'''
    )
    content = content.replace(
        '''{% if lot_nr %} · <span title="Lot Number">Lot: {{ lot_nr }}</span>{% endif %}''',
        f'''{{% if lot_nr %}} <span class="flex items-center ml-2" title="Lot Number">{box_svg}{{{{ lot_nr }}}}</span>{{% endif %}}'''
    )

    # Fallback to UTF-8 replaced strings if exact didn't match (due to encoding)
    content = re.sub(r'\{% if location %\} Â· <span class="text-\[var\(--text-primary\)\]">Loc: \{\{ location \}\}<\/span>\{% endif %\}', f'{{% if location %}} <span class="flex items-center text-[var(--color-sand)] ml-2" title="Location">{loc_svg}{{{{ location }}}}</span>{{% endif %}}', content)
    content = re.sub(r'\{% if lot_nr %\} Â· <span title="Lot Number">Lot: \{\{ lot_nr \}\}<\/span>\{% endif %\}', f'{{% if lot_nr %}} <span class="flex items-center ml-2" title="Lot Number">{box_svg}{{{{ lot_nr }}}}</span>{{% endif %}}', content)

    # Wrap the vendor/material div so it plays nice with the new flex layout if needed
    content = re.sub(r'<div class="text-xs soft-text mt-0\.5">\s*{{ vendor_name }}.*?{{ material_name }}\s*({% if location %}.*?{% endif %})\s*({% if lot_nr %}.*?{% endif %})\s*</div>', r'<div class="text-xs soft-text mt-0.5 flex flex-wrap items-center gap-1">\n                            <span>{{ vendor_name }} &middot; {{ material_name }}</span>\n                            \1\n                            \2\n                        </div>', content, flags=re.DOTALL)

    # 2. Extract and remove the old RFID row, and just put ID
    content = re.sub(
        r'<div class="text-xs mono text-right">\s*<div>ID {{ spool_id }}</div>\s*{% if rfid_uid %}\s*<div class="soft-text mt-0\.5" title="RFID UID: \{\{ rfid_uid \}\}">.*?\{\{ rfid_uid\|truncate\(8, True, \'\.\.\'\) \}\}<\/div>\s*{% endif %}\s*<\/div>',
        r'<div class="text-xs mono text-right">\n                        <div>ID {{ spool_id }}</div>\n                    </div>',
        content,
        flags=re.DOTALL
    )

    # Add the extracted full UID to the bottom of the card header (outside the flex row)
    header_end_regex = r'(<div class="text-xs mono text-right">\s*<div>ID \{\{ spool_id \}\}<\/div>\s*<\/div>\s*<\/div>)'
    replacement = r'\1\n                {% if rfid_uid %}\n                <div class="bg-[var(--surface-hover)] border border-edge rounded px-2 py-1.5 text-xs text-[#35AB57] flex items-center justify-between mt-2" title="RFID UID">\n                    <span class="flex items-center font-bold tracking-wide">' + tag_svg + r'{{ rfid_uid }}</span>\n                </div>\n                {% endif %}'
    content = re.sub(header_end_regex, replacement, content, count=1)

    # 3. Replacements for Temps
    content = re.sub(
        r'<div class="flex items-center gap-1" title="Temperatures">\s*.*?\{\{ extruder_temp.*?\}\}\s*\/\s*.*?\{\{ bed_temp.*?\}\}\s*<\/div>',
        f'<div class="flex items-center gap-3" title="Temperatures">\n                        <span class="flex items-center" title="Nozzle">{hot_svg}{{{{ extruder_temp ~ \'°C\' if extruder_temp else \'--\' }}}}</span>\n                        <span class="flex items-center" title="Bed">{bed_svg}{{{{ bed_temp ~ \'°C\' if bed_temp else \'--\' }}}}</span>\n                    </div>',
        content, flags=re.DOTALL
    )

    # 4. Add Confirmations to Buttons in spool card action area
    content = content.replace(
        '<button class="btn-outline text-xs w-full" title="Save live scale weight to Spoolman (subtracts empty spool automatically)">Re-weigh</button>',
        '<button class="btn-outline text-xs w-full" hx-confirm="Update Spoolman with the current live weight?" title="Save live scale weight to Spoolman (subtracts empty spool automatically)">Re-weigh</button>'
    )

    content = content.replace(
        '<button class="btn-outline text-xs w-full" title="Set remaining filament to 0g">Mark Used</button>',
        '<button class="btn-outline text-xs w-full" hx-confirm="Set remaining filament weight to 0g?" title="Set remaining filament to 0g">Mark Used</button>'
    )

    content = content.replace(
        '<button class="btn-outline text-xs w-full" title="Unlink RFID card from this spool">Unlink Tag</button>',
        '<button class="btn-outline text-xs w-full" hx-confirm="Unlink the RFID tag from this spool?" title="Unlink RFID card from this spool">Unlink Tag</button>'
    )

    content = content.replace(
        '<button class="btn-outline text-xs w-full text-[var(--color-sand)] border-[var(--color-sand)] hover:bg-[var(--color-sand)] hover:text-[#0b0e14]" title="Archive in Spoolman">Archive</button>',
        '<button class="btn-outline text-xs w-full text-[var(--color-sand)] border-[var(--color-sand)] hover:bg-[var(--color-sand)] hover:text-[#0b0e14]" hx-confirm="Archive this spool?" title="Archive in Spoolman">Archive</button>'
    )

    with open(filename, 'w', encoding='utf-8') as f:
        f.write(content)

update_file('templates/partials/spool_list.html')
