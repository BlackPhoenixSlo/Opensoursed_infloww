"use client";

/**
 * NotifSettingsPane — the bell's Settings tab (NotificationBell): this
 * browser's toasts, bubbles, OS ping and sounds (lib/notifSettings), and for
 * the owner the Agency feed's per-kind switches (`agency`, AgencyKindSwitches)
 * below them, so every notification setting sits in one place.
 */

import { Fragment, type ReactNode } from "react";

import { useNotificationSettings } from "@/hooks/useNotificationSettings";
import { ALERT_SOUNDS, isAlertSoundId, playAlertSound } from "@/lib/alertSounds";
import { ALERT_KINDS, NOTIF_TYPES, type SoundPref } from "@/lib/notifSettings";
import { OsPingSettings } from "./OsPingSettings";

export function NotifSettingsPane({ agency }: { agency?: ReactNode }) {
  const { settings, setToast, setBubble, update } = useNotificationSettings();
  return (
    <div className="flex-1 overflow-y-auto">
      <div className="border-b border-border p-2.5 bg-bg-elev-1/30">
        <div className="flex items-center justify-between mb-2 gap-2">
          <span className="text-[11px] font-medium text-fg">Notification settings</span>
          <label
            className="flex items-center gap-1.5 text-[11px] text-fg-dim cursor-pointer"
            title="Off mutes popups, badges and OS pings. The feed and the Buys & tips rail stay live."
          >
            <input
              type="checkbox"
              checked={settings.enabled}
              onChange={(e) => update({ enabled: e.target.checked })}
            />
            Enabled
          </label>
        </div>
        <div className="grid grid-cols-[1fr_auto_auto] gap-x-2 gap-y-1 text-[11px]">
          <span className="text-fg-dim">Type</span>
          <span className="text-fg-dim text-center w-12" title="Show toast">Toast</span>
          <span className="text-fg-dim text-center w-12" title="Bubble emphasis">Bubble</span>
          {NOTIF_TYPES.map((t) => (
            <Fragment key={t.key}>
              <span className="text-fg">{t.icon} {t.label}</span>
              <input
                type="checkbox"
                className="justify-self-center"
                aria-label={`${t.label} toast`}
                checked={settings.toast[t.key]}
                onChange={(e) => setToast(t.key, e.target.checked)}
                disabled={!settings.enabled}
              />
              <input
                type="checkbox"
                className="justify-self-center"
                aria-label={`${t.label} bubble`}
                checked={settings.bubble[t.key]}
                onChange={(e) => setBubble(t.key, e.target.checked)}
                disabled={!settings.enabled || !settings.toast[t.key]}
                title="Larger sticker + coloured ring"
              />
            </Fragment>
          ))}
        </div>
        <OsPingSettings settings={settings} update={update} />
        <div className="mt-2 grid grid-cols-[1fr_auto_auto] items-center gap-x-2 gap-y-1 text-[11px]">
          <span className="col-span-3 text-fg-dim">Sounds</span>
          {ALERT_KINDS.map((k) => {
            const pref = settings.sounds[k.key];
            const set = (patch: Partial<SoundPref>) =>
              update({ sounds: { ...settings.sounds, [k.key]: { ...pref, ...patch } } });
            return (
              <Fragment key={k.key}>
                <label className="flex items-center gap-1.5 text-fg cursor-pointer">
                  <input
                    type="checkbox"
                    checked={pref.on}
                    onChange={(e) => set({ on: e.target.checked })}
                    // The master toggle mutes the message sound; the reminder ignores it.
                    disabled={k.key === "message" && !settings.enabled}
                  />
                  {k.label}
                </label>
                <select
                  aria-label={`${k.label} sound`}
                  value={pref.sound}
                  onChange={(e) => {
                    if (!isAlertSoundId(e.target.value)) return;
                    set({ sound: e.target.value });
                    playAlertSound(e.target.value);
                  }}
                  className="bg-panel border border-border rounded px-1 py-0.5 text-[11px] text-fg"
                >
                  {ALERT_SOUNDS.map((s, i) => (
                    <option key={s.id} value={s.id}>{i + 1}. {s.label}</option>
                  ))}
                </select>
                <button
                  type="button"
                  onMouseDown={(e) => { e.stopPropagation(); }}
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    playAlertSound(pref.sound);
                  }}
                  className="w-6 h-6 grid place-items-center rounded border border-border text-fg-dim hover:text-fg hover:bg-bg-elev-1"
                  aria-label={`Preview ${k.label} sound`}
                  title="Preview"
                >
                  ▶
                </button>
              </Fragment>
            );
          })}
        </div>
      </div>
      {agency && (
        <div>
          <div className="px-3 pt-2.5 text-[11px] font-medium text-fg">Agency notifications</div>
          {agency}
        </div>
      )}
    </div>
  );
}
