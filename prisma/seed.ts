import { PrismaClient } from '@prisma/client';
import bcrypt from 'bcryptjs';

const prisma = new PrismaClient();

async function main() {
  console.log('🌱 Seeding database...');

  // Create default admin user
  const hashedPassword = await bcrypt.hash('admin123', 12);

  const admin = await prisma.user.upsert({
    where: { username: 'admin' },
    update: {},
    create: {
      username: 'admin',
      password: hashedPassword,
      role: 'admin',
    },
  });

  console.log(`✅ Admin user created: ${admin.username}`);

  // Create some sample settings
  const defaultSettings = [
    { key: 'site_name', value: 'DayZ News Monitor' },
    { key: 'check_interval', value: '5' },
    { key: 'publish_high_priority', value: 'true' },
    { key: 'publish_medium_priority', value: 'true' },
    { key: 'publish_low_priority', value: 'false' },
    { key: 'similarity_threshold', value: '0.85' },
  ];

  for (const setting of defaultSettings) {
    await prisma.settings.upsert({
      where: { key: setting.key },
      update: {},
      create: setting,
    });
  }

  console.log(`✅ ${defaultSettings.length} default settings created`);

  // Create sample sources
  const sampleSources = [
    {
      sourceType: 'discord',
      serverName: 'DayZ Official',
      sourceId: 'discord-official',
      channelName: 'announcements',
      enabled: true,
    },
    {
      sourceType: 'telegram',
      serverName: 'DayZ RU Community',
      sourceId: 'telegram-ru-community',
      channelName: 'general',
      enabled: true,
    },
    {
      sourceType: 'vk',
      serverName: 'DayZ Russia',
      sourceId: 'vk-dayz-russia',
      channelName: 'wall',
      enabled: true,
    },
    {
      sourceType: 'website',
      serverName: 'DayZ Official Blog',
      sourceId: 'https://dayz.com/blog',
      channelName: '',
      enabled: true,
    },
  ];

  for (const source of sampleSources) {
    await prisma.source.upsert({
      where: {
        id: source.sourceId,
      },
      update: {},
      create: {
        ...source,
        id: source.sourceId,
      },
    });
  }

  console.log(`✅ ${sampleSources.length} sample sources created`);

  // Create sample news items
  const now = new Date();
  const sampleNews = [
    {
      sourceId: 'discord-official',
      serverName: 'DayZ Official',
      title: 'Server Wipe Scheduled',
      content: 'The official DayZ server will undergo a full wipe on next Tuesday. All bases and items will be reset. Make sure to move your valuable items to a safe location.',
      summary: 'Scheduled server wipe for official DayZ server next Tuesday',
      newsType: 'wipe',
      priority: 'high',
      status: 'pending',
      createdAt: new Date(now.getTime() - 2 * 60 * 60 * 1000),
    },
    {
      sourceId: 'telegram-ru-community',
      serverName: 'DayZ RU Community',
      title: 'New Mod: Base Building Plus Updated',
      content: 'Base Building Plus mod has been updated to version 3.5. New features include reinforced walls, electric fences, and automated turrets.',
      summary: 'Base Building Plus mod update v3.5 with new defensive structures',
      newsType: 'update',
      priority: 'medium',
      status: 'approved',
      createdAt: new Date(now.getTime() - 5 * 60 * 60 * 1000),
      publishedAt: new Date(now.getTime() - 4 * 60 * 60 * 1000),
    },
    {
      sourceId: 'vk-dayz-russia',
      serverName: 'DayZ Russia',
      title: 'Community Event: PvP Tournament',
      content: 'A PvP tournament will be held this Saturday at 20:00 MSK. Teams of 4, prize pool includes unique weapon skins and base materials.',
      summary: 'Community PvP tournament this Saturday, teams of 4 with prize pool',
      newsType: 'event',
      priority: 'high',
      status: 'pending',
      createdAt: new Date(now.getTime() - 8 * 60 * 60 * 1000),
    },
    {
      sourceId: 'discord-official',
      serverName: 'DayZ Official',
      title: 'Patch 1.26 Hotfix Deployed',
      content: 'Hotfix deployed addressing performance issues, zombie AI pathfinding bugs, and vehicle desync. Server restart required.',
      summary: 'Hotfix for patch 1.26 fixing performance, zombie AI, and vehicle desync',
      newsType: 'patch',
      priority: 'high',
      status: 'approved',
      createdAt: new Date(now.getTime() - 12 * 60 * 60 * 1000),
      publishedAt: new Date(now.getTime() - 11 * 60 * 60 * 1000),
    },
    {
      sourceId: 'https://dayz.com/blog',
      serverName: 'DayZ Official Blog',
      title: 'Sakhal Map Development Update',
      content: 'The new Sakhal map is progressing well. We have finalized the terrain generation and are now working on point of interest locations. Expected release in Q1 2026.',
      summary: 'Development update on Sakhal map - terrain complete, working on POIs',
      newsType: 'update',
      priority: 'medium',
      status: 'pending',
      createdAt: new Date(now.getTime() - 24 * 60 * 60 * 1000),
    },
    {
      sourceId: 'telegram-ru-community',
      serverName: 'DayZ RU Community',
      title: 'Server Maintenance Notice',
      content: 'Community server will be down for maintenance on Thursday from 02:00 to 06:00 MSK for hardware upgrades and database optimization.',
      summary: 'Server maintenance scheduled Thursday 02:00-06:00 MSK',
      newsType: 'maintenance',
      priority: 'low',
      status: 'rejected',
      createdAt: new Date(now.getTime() - 30 * 60 * 60 * 1000),
    },
    {
      sourceId: 'discord-official',
      serverName: 'DayZ Official',
      title: 'New Weapons Coming in Update 1.27',
      content: 'Update 1.27 will introduce the AKS-74U, MP5K, and a new hunting rifle. Each weapon will have unique attachments and modifications.',
      summary: 'Three new weapons announced for update 1.27: AKS-74U, MP5K, hunting rifle',
      newsType: 'update',
      priority: 'medium',
      status: 'pending',
      createdAt: new Date(now.getTime() - 48 * 60 * 60 * 1000),
    },
    {
      sourceId: 'vk-dayz-russia',
      serverName: 'DayZ Russia',
      title: 'Raid Alert: NWAF Camp Under Attack',
      content: 'Multiple reports of a large group attacking the Northwest Airfield military camp. Players are advised to avoid the area.',
      summary: 'Large group attack reported at NWAF military camp, area warning issued',
      newsType: 'event',
      priority: 'high',
      status: 'approved',
      createdAt: new Date(now.getTime() - 50 * 60 * 60 * 1000),
      publishedAt: new Date(now.getTime() - 49 * 60 * 60 * 1000),
    },
    {
      sourceId: 'telegram-ru-community',
      serverName: 'DayZ RU Community',
      title: 'Trading Post Guidelines Updated',
      content: 'New rules for the trading post: maximum 5 listings per player, no scam reports will be processed, use middleman service for high-value trades.',
      summary: 'Updated trading post guidelines with new listing limits and rules',
      newsType: 'other',
      priority: 'low',
      status: 'pending',
      createdAt: new Date(now.getTime() - 72 * 60 * 60 * 1000),
    },
    {
      sourceId: 'https://dayz.com/blog',
      serverName: 'DayZ Official Blog',
      title: 'Frostline Expansion Details',
      content: 'Frostline expansion brings new winter mechanics, ice fishing, snowmobiles, and arctic survival elements. Full details and trailer coming next week.',
      summary: 'Frostline expansion with winter survival mechanics, ice fishing, snowmobiles',
      newsType: 'update',
      priority: 'high',
      status: 'approved',
      createdAt: new Date(now.getTime() - 96 * 60 * 60 * 1000),
      publishedAt: new Date(now.getTime() - 95 * 60 * 60 * 1000),
    },
  ];

  for (const news of sampleNews) {
    await prisma.newsItem.create({
      data: {
        ...news,
        externalId: '',
        channelName: '',
        author: '',
        formattedPost: news.content,
        images: '[]',
        links: '[]',
      },
    });
  }

  console.log(`✅ ${sampleNews.length} sample news items created`);

  console.log('\n🎉 Seeding complete!');
  console.log('   Admin: admin / admin123');
}

main()
  .catch((e) => {
    console.error('❌ Seed failed:', e);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
