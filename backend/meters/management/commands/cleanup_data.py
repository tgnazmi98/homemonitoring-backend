from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone
from datetime import timedelta
from meters.models import PowerReading, EnergyReading


class Command(BaseCommand):
    help = 'Clean up erroneous meter data from the database'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be deleted without actually deleting',
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Delete ALL data (use with caution!)',
        )
        parser.add_argument(
            '--stats',
            action='store_true',
            help='Show data statistics without deleting',
        )
        parser.add_argument(
            '--max-power',
            type=float,
            default=15000,
            help='Maximum valid power in Watts (default: 15000 for single-phase 63A)',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        delete_all = options['all']
        show_stats = options['stats']
        max_power = options['max_power']

        # Show statistics
        if show_stats:
            self.show_statistics()
            return

        if delete_all:
            self.delete_all_data(dry_run)
            return

        self.cleanup_erroneous_data(dry_run, max_power)

    def show_statistics(self):
        """Show data statistics to help identify issues"""
        self.stdout.write(self.style.WARNING('\n=== DATA STATISTICS ===\n'))

        # Power readings stats
        power_count = PowerReading.objects.count()
        self.stdout.write(f'Total power readings: {power_count}')

        if power_count > 0:
            from django.db.models import Min, Max, Avg

            power_stats = PowerReading.objects.aggregate(
                min_voltage=Min('voltage'),
                max_voltage=Max('voltage'),
                avg_voltage=Avg('voltage'),
                min_current=Min('current'),
                max_current=Max('current'),
                avg_current=Avg('current'),
                min_power=Min('active_power'),
                max_power=Max('active_power'),
                avg_power=Avg('active_power'),
            )

            self.stdout.write(f'\nPower Reading Stats:')
            self.stdout.write(f'  Voltage: min={power_stats["min_voltage"]:.1f}V, max={power_stats["max_voltage"]:.1f}V, avg={power_stats["avg_voltage"]:.1f}V')
            self.stdout.write(f'  Current: min={power_stats["min_current"]:.2f}A, max={power_stats["max_current"]:.2f}A, avg={power_stats["avg_current"]:.2f}A')
            self.stdout.write(f'  Power: min={power_stats["min_power"]:.0f}W, max={power_stats["max_power"]:.0f}W, avg={power_stats["avg_power"]:.0f}W')

            # Show sample recent readings
            self.stdout.write(f'\nRecent power readings (last 5):')
            recent = PowerReading.objects.order_by('-timestamp')[:5]
            for r in recent:
                self.stdout.write(f'  {r.timestamp}: V={r.voltage:.1f}, I={r.current:.2f}, P={r.active_power:.0f}W')

        # Energy readings stats
        energy_count = EnergyReading.objects.count()
        self.stdout.write(f'\nTotal energy readings: {energy_count}')

        if energy_count > 0:
            energy_stats = EnergyReading.objects.aggregate(
                min_import=Min('import_active_energy'),
                max_import=Max('import_active_energy'),
            )

            self.stdout.write(f'\nEnergy Reading Stats:')
            self.stdout.write(f'  Import Energy: min={energy_stats["min_import"]:.3f} kWh, max={energy_stats["max_import"]:.3f} kWh')

            # Show sample recent readings
            self.stdout.write(f'\nRecent energy readings (last 10):')
            recent = EnergyReading.objects.order_by('-timestamp')[:10]
            prev_energy = None
            for r in recent:
                delta_str = ""
                if prev_energy is not None and r.import_active_energy is not None:
                    # Note: since we're going backwards, delta is prev - current
                    delta = prev_energy - r.import_active_energy
                    if delta > 10:  # kWh - suspicious
                        delta_str = f" (delta: {delta:.3f} kWh - SUSPICIOUS!)"
                    else:
                        delta_str = f" (delta: {delta:.3f} kWh)"
                prev_energy = r.import_active_energy
                self.stdout.write(f'  {r.timestamp}: {r.import_active_energy:.3f} kWh{delta_str}')

            # Check for large deltas (gaps in readings)
            self.stdout.write(f'\n=== Checking for suspicious deltas ===')
            readings = list(EnergyReading.objects.order_by('timestamp').values('timestamp', 'import_active_energy')[:1000])
            suspicious_count = 0
            for i in range(1, len(readings)):
                prev = readings[i-1]['import_active_energy'] or 0
                curr = readings[i]['import_active_energy'] or 0
                delta = curr - prev
                if delta > 10:  # > 10 kWh in one reading is suspicious for residential
                    suspicious_count += 1
                    if suspicious_count <= 5:
                        self.stdout.write(f'  Suspicious delta at {readings[i]["timestamp"]}: {delta:.3f} kWh')

            self.stdout.write(f'\nTotal suspicious deltas (>10 kWh): {suspicious_count}')

    def delete_all_data(self, dry_run):
        """Delete all data from both tables"""
        self.stdout.write(self.style.WARNING('Deleting ALL data...'))

        power_count = PowerReading.objects.count()
        energy_count = EnergyReading.objects.count()

        if not dry_run:
            PowerReading.objects.all().delete()
            EnergyReading.objects.all().delete()
            self.stdout.write(self.style.SUCCESS(
                f'Deleted {power_count} power readings and {energy_count} energy readings'
            ))
        else:
            self.stdout.write(self.style.WARNING(
                f'[DRY RUN] Would delete {power_count} power readings and {energy_count} energy readings'
            ))

    def cleanup_erroneous_data(self, dry_run, max_power):
        """Clean up erroneous readings based on physical limits"""

        self.stdout.write('Identifying erroneous power readings...')

        # Power readings with invalid values
        # For single-phase 63A/230V: max power ~14.5kW
        erroneous_power = PowerReading.objects.filter(
            Q(voltage__lt=100) | Q(voltage__gt=300) |  # Voltage way out of range
            Q(voltage__isnull=True, current__isnull=True, active_power__isnull=True) |  # All null
            Q(current__lt=0) | Q(current__gt=100) |  # Invalid current (max 63A + margin)
            Q(active_power__lt=-1000) | Q(active_power__gt=max_power) |  # Power out of range
            Q(power_factor__lt=-0.1) | Q(power_factor__gt=1.5) |  # Invalid power factor
            Q(frequency__lt=45) | Q(frequency__gt=55)  # Frequency way out of range
        )

        erroneous_power_count = erroneous_power.count()

        self.stdout.write('Identifying erroneous energy readings...')

        # Energy readings with invalid values
        erroneous_energy = EnergyReading.objects.filter(
            Q(import_active_energy__lt=0) |  # Negative cumulative energy
            Q(export_active_energy__lt=0) |
            Q(power_demand__lt=0) | Q(power_demand__gt=max_power)  # Invalid demand
        )

        erroneous_energy_count = erroneous_energy.count()

        # Show summary
        total_power = PowerReading.objects.count()
        total_energy = EnergyReading.objects.count()

        self.stdout.write(f'\nPower readings: {erroneous_power_count}/{total_power} erroneous')
        self.stdout.write(f'Energy readings: {erroneous_energy_count}/{total_energy} erroneous')

        if erroneous_power_count > 0:
            self.stdout.write('\nSample erroneous power readings:')
            for reading in erroneous_power[:5]:
                self.stdout.write(
                    f'  {reading.timestamp} - V:{reading.voltage}, I:{reading.current}, '
                    f'P:{reading.active_power}, PF:{reading.power_factor}, F:{reading.frequency}'
                )

        if erroneous_energy_count > 0:
            self.stdout.write('\nSample erroneous energy readings:')
            for reading in erroneous_energy[:5]:
                self.stdout.write(
                    f'  {reading.timestamp} - Import:{reading.import_active_energy}, '
                    f'Export:{reading.export_active_energy}, Demand:{reading.power_demand}'
                )

        if not dry_run:
            if erroneous_power_count > 0:
                erroneous_power.delete()
                self.stdout.write(self.style.SUCCESS(
                    f'Deleted {erroneous_power_count} erroneous power readings'
                ))

            if erroneous_energy_count > 0:
                erroneous_energy.delete()
                self.stdout.write(self.style.SUCCESS(
                    f'Deleted {erroneous_energy_count} erroneous energy readings'
                ))

            if erroneous_power_count == 0 and erroneous_energy_count == 0:
                self.stdout.write(self.style.SUCCESS('No erroneous data found!'))
        else:
            self.stdout.write(self.style.WARNING(
                f'\n[DRY RUN] Would delete {erroneous_power_count} power and '
                f'{erroneous_energy_count} energy readings'
            ))
            self.stdout.write('Run without --dry-run to actually delete')
