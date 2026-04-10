import re

with open('templates/partials/spool_list.html', 'r', encoding='utf-8') as f:
    content = f.read()

new_html = r"""            <div class="p-3 rounded border border-edge spool-item bg-[var(--surface)] hover:border-gray-500 transition-colors shadow-sm" data-material="{{ (material_name|lower) }}" data-remaining="{{ remaining }}" data-search="{{ (filament_name ~ ' ' ~ material_name ~ ' ' ~ vendor_name ~ ' ' ~ spool_id)|lower }}">
                
                <!-- Spool Header -->
                <div class="flex justify-between items-start gap-3 mb-3">
                    <div class="flex flex-1 gap-2 items-center min-w-0">
                        {% if color_hex %}
                        <div class="w-4 h-4 rounded-full border border-edge shrink-0 shadow-sm" style="background-color: #{{ color_hex|replace('#', '') }};"></div>
                        {% endif %}
                        <div class="min-w-0 flex-1">
                            <div class="font-bold text-[var(--text-primary)] truncate text-base leading-tight">{{ filament_name }}</div>
                            <div class="text-xs soft-text font-medium mt-1 flex flex-wrap gap-1.5 items-center">
                                <span class="px-1.5 py-0.5 rounded bg-[var(--surface-hover)] border border-edge shadow-sm text-[var(--text-primary)]">{{ material_name }}</span>
                                <span>{{ vendor_name }}</span>
                                {% if location %}<span class="text-[#35AB57] border border-edge rounded px-1.5 py-0.5 shadow-sm">📍 {{ location }}</span>{% endif %}
                                {% if lot_nr %}<span title="Lot Number">📦 {{ lot_nr }}</span>{% endif %}
                            </div>
                        </div>
                    </div>
                    <div class="text-xs mono text-right shrink-0 bg-[var(--surface-hover)] border border-edge px-2 py-1.5 rounded shadow-sm">
                        <div class="soft-text">ID: <span class="font-bold text-[var(--text-primary)] text-sm ml-0.5">{{ spool_id }}</span></div>
                        {% if rfid_uid %}
                        <div class="text-[#35AB57] mt-1" title="RFID UID: {{ rfid_uid }}">🏷️ {{ rfid_uid|truncate(8, True, '..') }}</div>
                        {% endif %}
                    </div>
                </div>

                <!-- Stats Grid -->
                <div class="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-3">
                    <div class="bg-[var(--surface-hover)] rounded py-1.5 px-2 flex flex-col items-center justify-center border border-edge relative shadow-sm text-center">
                        <span class="soft-text uppercase text-[0.6rem] font-bold tracking-wider mb-0.5">Remaining</span>
                        <div class="w-full flex flex-col items-center">
                            <span class="mono text-[var(--text-primary)] font-bold text-sm">{{ "%.1f"|format(remaining if remaining is not none else 0) }}<span class="soft-text font-normal text-[0.65rem] ml-0.5">g</span></span>
                            {% if total > 0 %}
                            <div class="w-10/12 bg-[#141820] rounded-full h-1 mt-1 border border-edge overflow-hidden">
                                <div class="bg-accent-gradient h-full rounded-full" style="width: {{ [100, (remaining / total * 100)]|min }}%"></div>
                            </div>
                            {% endif %}
                        </div>
                    </div>

                    <div class="bg-[var(--surface-hover)] rounded py-1.5 px-2 flex flex-col items-center justify-center border border-edge relative shadow-sm text-center">
                        <span class="soft-text uppercase text-[0.6rem] font-bold tracking-wider mb-0.5">Measured</span>
                        <span class="mono text-blue-400 font-bold text-sm">{{ "%.1f"|format(measured) }}<span class="soft-text font-normal text-[0.65rem] ml-0.5">g</span></span>
                        <span class="soft-text text-[0.6rem] mt-0.5" title="Empty Spool Weight">-{{ "%.0f"|format(empty_weight) }}g<span class="hidden lg:inline"> (Empty)</span></span>
                    </div>

                    <div class="bg-[var(--surface-hover)] rounded py-1.5 px-2 flex flex-col items-center justify-center border border-edge shadow-sm text-center">
                        <span class="soft-text uppercase text-[0.6rem] font-bold tracking-wider mb-0.5">Capacity</span>
                        <span class="mono font-bold text-sm text-[var(--text-primary)]">{{ "%.1f"|format(total if total is not none else 0) }}<span class="soft-text font-normal text-[0.65rem] ml-0.5">g</span></span>
                    </div>

                    <div class="bg-[var(--surface-hover)] rounded py-1 px-1.5 flex flex-col items-center justify-center border border-edge shadow-sm text-center soft-text text-xs">
                        {% if extruder_temp or bed_temp %}
                            <div class="font-bold text-[var(--text-primary)] mb-0.5 flex items-center justify-center gap-1" title="Nozzle Temp"><span class="text-xs">🔥</span> {{ extruder_temp|string|truncate(4, True, '') ~ '°' if extruder_temp else '--' }}</div>
                            <div class="font-bold flex items-center justify-center gap-1" title="Bed Temp"><span class="text-xs">🛏️</span> {{ bed_temp|string|truncate(4, True, '') ~ '°' if bed_temp else '--' }}</div>
                        {% else %}
                            <span class="italic opacity-50 text-[0.65rem]">No Temps</span>
                        {% endif %}
                    </div>
                </div>

                <!-- Action Buttons -->
                <div class="flex flex-wrap gap-2 pt-3 mt-1 border-t border-edge">
                    <form hx-post="/filaments/spoolman/action" hx-target="#spool-list-wrapper" hx-swap="innerHTML" class="flex-1 min-w-[70px]">
                        <input type="hidden" name="action" value="reweigh">
                        <input type="hidden" name="spool_id" value="{{ spool_id }}">
                        <input type="hidden" name="weight" value="{{ weight_grams if weight_grams is not none else measured }}">
                        <input type="hidden" name="empty_weight" value="{{ empty_weight }}">
                        <button class="btn-blue text-xs w-full py-1.5 shadow-sm" title="Save live scale weight to Spoolman (subtracts empty spool automatically)">Re-weigh</button>
                    </form>
                    <form hx-post="/filaments/spoolman/action" hx-target="#spool-list-wrapper" hx-swap="innerHTML" class="flex-1 min-w-[70px]">
                        <input type="hidden" name="action" value="mark_used">
                        <input type="hidden" name="spool_id" value="{{ spool_id }}">
                        <button class="btn-outline text-xs w-full py-1.5 shadow-sm" title="Set remaining filament to 0g">Mark Used</button>
                    </form>
                    <form hx-post="/filaments/spoolman/action" hx-target="#spool-list-wrapper" hx-swap="innerHTML" class="flex-1 min-w-[70px]">
                        <input type="hidden" name="action" value="unlink">
                        <input type="hidden" name="spool_id" value="{{ spool_id }}">
                        <button class="btn-outline text-xs w-full py-1.5 shadow-sm" title="Unlink RFID card from this spool">Unlink</button>
                    </form>
                    <form hx-post="/filaments/spoolman/action" hx-target="#spool-list-wrapper" hx-swap="innerHTML" class="flex-1 min-w-[70px]">
                        <input type="hidden" name="action" value="archive">
                        <input type="hidden" name="spool_id" value="{{ spool_id }}">
                        <button class="btn-outline text-xs w-full py-1.5 shadow-sm text-[var(--color-sand)] border-[var(--color-sand)] hover:bg-[var(--color-sand)] hover:text-[#0b0e14]" title="Archive in Spoolman">Archive</button>
                    </form>
                    <form hx-post="/filaments/spoolman/action" hx-target="#spool-list-wrapper" hx-swap="innerHTML" class="shrink-0 flex items-center">
                        <input type="hidden" name="action" value="remove">
                        <input type="hidden" name="spool_id" value="{{ spool_id }}">
                        <button class="btn-outline text-xs h-full px-3.5 shadow-sm text-[#E72A2E] border-[#E72A2E] hover:bg-[#E72A2E] hover:text-white" hx-confirm="Are you sure you want to permanently delete this spool from Spoolman? Consider 'Archive' instead." title="Delete from Spoolman permanently">🗑️</button>
                    </form>
                </div>
            </div>"""

pattern = re.compile(r'<div class="p-3 rounded border space-y-2 border-edge spool-item".*?</div>\s*</div>\s*</div>\s*</div>\s*</div>', flags=re.DOTALL)
new_content = pattern.sub(new_html, content)

with open('templates/partials/spool_list.html', 'w', encoding='utf-8') as f:
    f.write(new_content)